import os
from dotenv import load_dotenv
from .prompt_llm import *
from .Scenario_description import Scenario
import json
from openai import OpenAI
import numpy as np
import gym
import re

# 自动加载 .env 文件（每个环境有自己的 .env，不进 git）
load_dotenv(override=True)

# 用环境变量配置 LLM，便于在不同环境间切换（Windows/Linux/云端）
api_key = os.getenv("LLM_API_KEY", "ollama")
SILICONFLOW_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
SILICONFLOW_MODEL = os.getenv("LLM_MODEL", "qwen2.5:32b")

# 进程级单例 OpenAI 客户端：避免每次请求新建 client 造成 socket/fd 泄漏
# （长时间大批量请求会出现 "Too many open files" / "Device or resource busy"）
_llm_client = None


def _get_llm_client():
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenAI(
            api_key=api_key,
            base_url=SILICONFLOW_BASE_URL,
            timeout=1800.0,   # 本地 27B/32B 模型单次生成可能较慢，给足超时
            max_retries=1,    # 连接失败仅重试 1 次，避免反复建连加剧 fd 压力
        )
    return _llm_client


# ==================== 方向D：覆盖度感知记忆签名 ====================
# 记忆库最小可用条目数：低于该值不产生 coverage_signal（库太小不敢信，设计稿 §5.4）
MEMORY_MIN_LIBRARY_SIZE = 5
# 密度分桶阈值（用 reset 后的车数分桶）：<=DENSITY_SPARSE_MAX 为 sparse，
# <=DENSITY_NORMAL_MAX 为 normal，其余 dense。阈值要在服务器"参数体检"
# （设计稿 §7 步骤 0）拿到实测车数后按实际分布标定。
DENSITY_SPARSE_MAX = 8
DENSITY_NORMAL_MAX = 16


def density_bucket(n_vehicles):
    """把 reset 后的车数分成 sparse / normal / dense 三档（签名成分之一，设计稿 §3.4）。"""
    if n_vehicles is None:
        return 'normal'
    if n_vehicles <= DENSITY_SPARSE_MAX:
        return 'sparse'
    if n_vehicles <= DENSITY_NORMAL_MAX:
        return 'normal'
    return 'dense'


def conflict_direction_label(ego_veh, other_veh):
    """冲突车相对 ego 的方位：ahead / ahead-left / ahead-right（设计稿 §3.3）。"""
    if other_veh is None:
        return 'ahead'
    dx = other_veh.position[0] - ego_veh.position[0]
    dy = other_veh.position[1] - ego_veh.position[1]
    # 以 ego 的 heading 为参考方向，得到相对方位角（逆时针为正 = 左侧）
    angle = np.degrees(np.arctan2(dy, dx)) - np.degrees(ego_veh.heading)
    angle = (angle + 180.0) % 360.0 - 180.0
    if abs(angle) < 45.0:
        return 'ahead'
    if abs(angle) > 135.0:
        # 正后方：冲突检测只看前方（llm_agent_negotiation_system.py:118），正常不会出现
        return 'ahead'
    return 'ahead-left' if angle > 0 else 'ahead-right'


def select_conflicting_vehicle(ego_veh, negotiation_results, conflicting_info, env):
    """挑出"最危险冲突"里与 ego 冲突的那辆车，用于判定冲突方位。

    口径与 prompt_llm.check_safety_with_conflict_vehicles 一致：只在"建议 ego 让行
    (passes second)"的冲突车里，取 |ΔTTCP| 最大的一组。找不到返回 None。
    """
    if not conflicting_info:
        return None
    pattern = re.compile(r"- You have conflict with (MDPVehicle #[0-9]+|IDMVehicle #[0-9]+). It is suggested that you should passes second.")
    vehicles_pass_second = pattern.findall(negotiation_results or "")
    if not vehicles_pass_second:
        return None
    try:
        speed_limit = env.road.network.get_lane(ego_veh.lane_index).speed_limit
    except Exception:
        speed_limit = 5
    best_vehicle, best_abs_ttcp = None, -1.0
    for vehicle in vehicles_pass_second:
        for conflict_group in conflicting_info:
            other_veh = None
            if conflict_group['vehicle_i'] == ego_veh and str(conflict_group['vehicle_j']).split(':')[0].strip() == vehicle:
                other_veh = conflict_group['vehicle_j']
            elif conflict_group['vehicle_j'] == ego_veh and str(conflict_group['vehicle_i']).split(':')[0].strip() == vehicle:
                other_veh = conflict_group['vehicle_i']
            if other_veh is None:
                continue
            ttcp_i = cal_ttcp(speed_limit, conflict_group['vehicle_i distance to conflict'], conflict_group['vehicle_i speed'])
            ttcp_j = cal_ttcp(speed_limit, conflict_group['vehicle_j distance to conflict'], conflict_group['vehicle_j speed'])
            if abs(ttcp_j - ttcp_i) > best_abs_ttcp:
                best_abs_ttcp = abs(ttcp_j - ttcp_i)
                best_vehicle = other_veh
    return best_vehicle


def build_memory_signature(ego_veh, env, conflicting_info, negotiation_results,
                           most_dangerous_info, n_vehicles=None, conflict_direction=None):
    """构造"覆盖度感知记忆签名"（设计稿 §3，改动清单 #1）。

    返回 (signature, relation, delta_speed)：
      signature   —— 写库与检索共用的签名文本；
      relation    —— 5 档关系；无冲突时为 None（写库 comments 走 'recommended to FASTER' 分支）；
      delta_speed —— 速度差；无冲突时为 None。

    签名独立构造、不改动 prompt_info 的任何字符（设计稿 §1），
    所以 --memory-signature orig 时既不影响原 prompt，也不影响已跑出的实验结果。
    """
    if n_vehicles is None:
        n_vehicles = len(env.road.vehicles)
    density = density_bucket(n_vehicles)
    delta_ttcp = most_dangerous_info.get('delta ttcp') if most_dangerous_info else None
    if delta_ttcp is None:
        # 无冲突（设计稿 §3.2）：原实现写库的是常量 ' Conflict info is empty'，
        # 库里会堆积大量逐字相同条目、稀释判别力；改后无冲突步文本也随场景变化。
        signature = (f"No conflict with other vehicles now. Traffic density is {density}, "
                     f"{n_vehicles} vehicles on road.")
        return signature, None, None

    relation = relation_from_delta_ttcp(delta_ttcp)
    delta_speed = most_dangerous_info.get('delta speed')
    n_conflicts = len(conflicting_info) if conflicting_info else 0
    if conflict_direction is None:
        conflict_direction = conflict_direction_label(
            ego_veh, select_conflicting_vehicle(ego_veh, negotiation_results, conflicting_info, env))
    signature = (f"Ego is {relation} to conflict point than other vehicles, "
                 f"ego speed minus other vehicle speed is {delta_speed} m/s. "
                 f"Traffic density is {density}, {n_vehicles} vehicles on road, "
                 f"{n_conflicts} conflict(s) ahead, conflict approach from {conflict_direction}.")
    return signature, relation, delta_speed


def apply_coverage_degradation(llm_action, coverage_signal, dangerous_level, th_a, th_b):
    """覆盖度降级（设计稿 §6.2，改动清单 #7）。

    "这个场景我不熟" 等价于 "危险等级上调一档"：
      coverage_penalty = 0（熟 / 无信号） / 1（有点生） / 2（很生）
      effective_level  = min(3, dangerous_level + coverage_penalty)
      effective_level 1、2 → 禁止加速：FASTER(3) → IDLE(1)
      effective_level 3    → 强制减速：SLOWER(4)

    返回 (final_action, effective_level)。
    """
    penalty = 0
    if coverage_signal is not None and th_a is not None and th_b is not None:
        if coverage_signal > th_b:
            penalty = 2
        elif coverage_signal > th_a:
            penalty = 1
    effective_level = min(3, int(dangerous_level or 0) + penalty)

    action_id = int(np.asarray(llm_action).reshape(-1)[0])
    final_id = action_id
    if effective_level == 3:
        final_id = 4   # SLOWER
    elif effective_level in (1, 2) and action_id == 3:
        final_id = 1   # FASTER → IDLE
    return np.array([final_id]), effective_level


class LlmAgent_action_module():
    def __init__(self, env):
        # self.env = env
        # self.action_space = self.env.action_space
        # self.observation_space = self.env.observation_space
        self.sce = Scenario(env.road, vehicleCount=10)
        self.frame = 0
        # self.obs = self.env.reset()
        self.done = False
        self.parse_failures = 0  # 统计 LLM 输出解析失败次数（用于 progress.json）
        self.toolModels = [
            getAvailableActions(),
            getAvailableLanes(self.sce),
            getLaneInvolvedCar(self.sce),
            isChangeLaneConflictWithCar(self.sce),
            isAccelerationConflictWithCar(self.sce),
            isKeepSpeedConflictWithCar(self.sce),
            isDecelerationSafe(self.sce),
        ]
        self.pre_prompt = PRE_DEF_PROMPT()
        self.get_actions(env)


    def llm_controller_run(self, env, negotiation_prompt, conflicting_info, controlled_vehicles, memory,
                           use_memory=False, memory_top_k=2, memory_update=False,
                           memory_signature_kind='orig', coverage_guard=False,
                           th_a=None, th_b=None, log_ctx=None, n_vehicles_fixed=None):
        self.parse_failures = 0  # 重置本回合解析失败计数
        llm_actions = []
        step_records = []  # 每步每车一条记录，供离线分析（设计稿 §5）
        log_ctx = log_ctx or {}
        if n_vehicles_fixed is None:
            n_vehicles_fixed = len(env.road.vehicles)  # 签名用"reset 后车数"，整集内固定
        for i, ego_veh in enumerate(controlled_vehicles):
            scene_name = self.get_scene_name(env)
            if scene_name == 'intersection':
                speed_limit = 5
            else:
                speed_limit = 20
            ego_veh.speed = speed_limit if ego_veh.speed > speed_limit else ego_veh.speed
            negotiation_results = self.transfer_negotiation_prompts_to_results(ego_veh, negotiation_prompt)
            prompt_info, sig_info = self.prompt_engineer(ego_veh, env.road, env, negotiation_results,
                                                         conflicting_info,
                                                         n_vehicles=n_vehicles_fixed)  # prompt engineer
            # print("prompt_info:", prompt_info)
            llm_action, coverage_signal, topk_actions, library_size = self.send_to_chatgpt(
                ego_veh, prompt_info, negotiation_results, memory,
                use_memory=use_memory, memory_top_k=memory_top_k,
                memory_signature_kind=memory_signature_kind,
                signature_new=sig_info['signature_new'])
            # 覆盖度降级：只在 intersection/merge（is_intersection=True）且显式开启 --coverage-guard 时生效
            final_action = llm_action
            effective_level = sig_info['dangerous_level']
            if coverage_guard and self.is_intersection:
                final_action, effective_level = apply_coverage_degradation(
                    llm_action, coverage_signal, sig_info['dangerous_level'], th_a, th_b)
            if memory_update and memory is not None:
                self.memory_update(memory, prompt_info, llm_action,
                                   relation=sig_info['relation'],
                                   signature=sig_info['signature_' + memory_signature_kind],
                                   memory_signature_kind=memory_signature_kind)
            llm_actions.append(final_action)
            step_records.append({
                'episode': log_ctx.get('episode'),
                'step': log_ctx.get('step'),
                'split': log_ctx.get('split'),
                'vehicle_id': str(ego_veh),
                'n_vehicles': n_vehicles_fixed,             # reset 后车数，整集固定，签名就用它
                'n_vehicles_step': len(env.road.vehicles),  # 当步车数，仅诊断，不进签名
                'n_conflicts': sig_info['n_conflicts'],
                'conflict_direction': sig_info['conflict_direction'],
                'relation': sig_info['relation'],
                'delta_speed': sig_info['delta_speed'],
                'signature_orig': sig_info['signature_orig'],
                'signature_new': sig_info['signature_new'],
                'retrieval_scores': topk_scores,
                'retrieved_actions': topk_actions,
                'library_size': library_size,
                'llm_action': int(np.asarray(llm_action).reshape(-1)[0]),
                'final_action': int(np.asarray(final_action).reshape(-1)[0]),
                'coverage_signal': coverage_signal,
                'dangerous_level': sig_info['dangerous_level'],
                'effective_level': effective_level,
            })
            print("llm_action:", final_action, ego_veh, 'speed now:', ego_veh.speed)
        return llm_actions, step_records

    def get_scene_name(self, env):
        scene_name = env.spec.id
        match = re.search(r'(merge|intersection|highway)', scene_name)
        simplified_scene_name = match.group(0) if match else 'unknown'
        return simplified_scene_name

    def get_actions(self, env):
        scene_name = self.get_scene_name(env)
        if scene_name == 'highway':
            self.ACTIONS_ALL = {
                0: 'LANE_LEFT',
                1: 'IDLE',
                2: 'LANE_RIGHT',
                3: 'FASTER',
                4: 'SLOWER'
            }
            self.is_intersection = False
        elif scene_name == 'merge' or scene_name == 'intersection':
            self.ACTIONS_ALL = {
                1: 'IDLE',
                3: 'FASTER',
                4: 'SLOWER',
            }
            self.is_intersection = True
        else:
            self.ACTIONS_ALL = None
            self.is_intersection = None

    def retrun_sce(self):
        return self.sce

    def render(self):
        self.env.render()

    def close(self):
        self.env.close()

    def get_action_id_from_name(self, action_name, actions_all):
        """
        Get the action ID corresponding to the given action name.

        Parameters:
        action_name (str): The name of the action (e.g., 'LANE_LEFT').
        actions_all (dict): Dictionary mapping IDs to action names.

        Returns:
        int: The ID corresponding to the action name, or 1 (IDLE) if not found.
        """
        for id, name in actions_all.items():
            if name == action_name or name == action_name.upper():
                return id
        # Fallback: 返回 IDLE 的 id（最安全动作，避免 KeyError 崩溃）
        return 1

    def transfer_negotiation_prompts_to_results(self, ego_veh, negotiation_prompt):
        vehicle_conflicts = self.extract_vehicle_conflicts(negotiation_prompt, str(ego_veh).split(":")[0].strip())
        negotiation_results = ""
        for conflict in vehicle_conflicts:
            first_vehicle, second_vehicle, order = conflict
            if first_vehicle == str(ego_veh).split(":")[0].strip():
                negotiation_results += f"- You have conflict with {second_vehicle}. It is suggested that you should {'passes first' if order == 'first' else 'passes second'}.\n"
            else:
                negotiation_results += f"- You have conflict with {first_vehicle}. It is suggested that you should {'passes first' if order == 'first' else 'passes second'}.\n"
        return negotiation_results

    def relative_memory(self, memory, prompt_info, top_k=2, memory_signature_kind='orig', signature_new=None):
        """检索相似经验（改动清单 #4）。

        返回 (experience, topk_scores, topk_actions)：
          experience  —— 拼进 prompt 的经验文本；orig 分支与改动前逐字一致；
          topk_scores —— top-k 检索距离（覆盖度信号用，只在日志/降级里用，不进 prompt）；
          topk_actions—— top-k 检索到的历史动作（一致性维度，本次不做分析）。
        """
        experience = ""
        if memory_signature_kind == 'new':
            # 新签名：检索文本与写库文本同口径（都是覆盖度感知签名）
            query_scenario = signature_new if signature_new else prompt_info.strip().split('\n')[-1]
        else:
            # 原签名：保持论文实现的"prompt_info 最后两行"作为检索文本（逐字不变）
            extract_prompt = prompt_info.strip().split('\n')
            query_scenario = '\n'.join(extract_prompt[-2:])  # only save the last two line of prompt_info which store the most dangerous conflict as memory page_content
        library_size = memory.memory_size()
        past_decisions = []
        if library_size > 0:
            # top_k 大于库容量时按库容量取，避免 Chroma 报错 / 返回重复条目（设计稿 §5.4）
            past_decisions = memory.retrieveMemory(query_scenario, top_k=min(top_k, library_size))
        for past_decision in past_decisions:
            experience += f"- Last time {past_decision['negotiation_result']}, you choose to {past_decision['final_action']}, it is {past_decision['comments']}\n"
        experience += f"Above messages are some examples of how you make a decision in the past. Those scenarios are similar to the current scenario. You should refer to those examples to make a decision for the current scenario."
        topk_scores = [past_decision.get('retrieval_score') for past_decision in past_decisions]
        topk_actions = [past_decision.get('final_action') for past_decision in past_decisions]
        return experience, topk_scores, topk_actions

    def memory_update(self, memory, prompt_info, llm_action, relation=None, signature=None,
                      memory_signature_kind='orig'):
        """写入一条记忆（改动清单 #5）。

        orig 分支：完全保留原实现（写 prompt_info 最后一行 + 正则解析 relation）；
        new 分支：写覆盖度感知签名文本，relation 由调用方直接传入，不再做正则解析。
        """
        human_question = str(None)
        negotiation = str(None)  # memory store the dangerous info (which negotiation is ego to yield) for ego vehicle
        action = str(llm_action)
        if memory_signature_kind == 'new':
            saved_info = signature if signature is not None else prompt_info.strip().split('\n')[-1]
            if relation is not None:
                comments = generate_comment(relation, llm_action[0])
                print(relation, llm_action[0], comments)
            else:
                # 无冲突步：与原来的 ' Conflict info is empty' 分支一致
                comments = 'recommended to FASTER'
        else:
            saved_info = prompt_info.strip().split('\n')[-1]
            if saved_info != ' Conflict info is empty':
                saved_relation = re.findall(r'_(.*?)_', saved_info)
                comments = generate_comment(saved_relation[0], llm_action[0])
                print(saved_relation[0], llm_action[0], comments)
            else:
                comments = 'recommended to FASTER'
        memory.addMemory(str(saved_info), human_question, negotiation, action, comments)
        print(' New mem has been added ...')


    def send_to_chatgpt(self, ego_veh, current_scenario, negotiation_results, memory, use_memory=False, memory_top_k=2, memory_update=False,
                        memory_signature_kind='orig', signature_new=None):
        """问 LLM 要决策（改动清单 #6）。

        返回 (llm_action, coverage_signal, topk_actions, library_size)：
          coverage_signal = top-k 检索距离的均值（见设计稿 §6.2，口径与离线判据一致）；
          库条目数 < MEMORY_MIN_LIBRARY_SIZE 时 coverage_signal 记为 None（不触发降级）。
        """
        # 复用进程级单例客户端（防止 fd 泄漏），连接池自动复用
        client = _get_llm_client()

        if self.is_intersection:
            message_prefix = self.pre_prompt.SYSTEM_MESSAGE_PREFIX_intersection
            traffic_rules = self.pre_prompt.get_traffic_rules(self.is_intersection)
            decision_cautions = self.pre_prompt.get_decision_cautions(self.is_intersection)
        else:
            message_prefix = self.pre_prompt.SYSTEM_MESSAGE_PREFIX
            traffic_rules = self.pre_prompt.get_traffic_rules()
            decision_cautions = self.pre_prompt.get_decision_cautions()
        # action_name = ACTIONS_ALL.get(action_id, "Unknown Action")
        # action_description = ACTIONS_DESCRIPTION.get(action_id, "No description available")
        # past_memory = self.relative_memory(memory, current_scenario)  # with this line to active memory retrivel, active line46 to build your own database before you output past memory
        topk_scores, topk_actions, library_size = [], [], 0
        if use_memory:
            past_memory, topk_scores, topk_actions = self.relative_memory(
                memory, current_scenario, memory_top_k,
                memory_signature_kind=memory_signature_kind, signature_new=signature_new)
            library_size = memory.memory_size()
        else:
            past_memory = ''
        # 覆盖度信号 = top-k 检索距离均值；库太小（< MEMORY_MIN_LIBRARY_SIZE）时不产生信号
        coverage_signal = None
        valid_scores = [s for s in topk_scores if s is not None]
        if use_memory and library_size >= MEMORY_MIN_LIBRARY_SIZE and valid_scores:
            coverage_signal = float(np.mean(valid_scores))

        prompt = (f"{message_prefix}"
                  f"You, the 'ego' car, are now driving. You have already driven for some seconds.\n"
                  "Here is the current scenario:\n"
                  f"{current_scenario}\n\n"
                  "There are several rules you need to follow when you drive:\n"
                  f"{traffic_rules}\n\n"
                  "Here are your attention points:\n"
                  f"{decision_cautions}\n\n"
                  "Here is your action when scenarios are similar to the current scenario in the past, you should learn from past memory try not to take the cation that cause more danger:\n"
                  f"{past_memory}\n\n"
                  "Based on the planning trajectory, you have the following conflicts with other vehicles.\n"
                  "Here are the conflicts and the suggested passing orders (when you are suggested to passes second, better to slow down): \n"
                  f"{negotiation_results}\n\n"
                  "Once you make a final decision, output it in the following format:\n"
                  "```\n"
                  "Final Answer: \n"
                  "    \"decision\": {\"<ego car's decision, ONE of the available actions (decision have to be one of the following action!!!:  LANE_LEFT, IDLE, LANE_RIGHT, FASTER, SLOWER)>\"},\n"
                  "```\n"
                  "\n"
                  "Example of a correct response:\n"
                  "Final Answer:\n"
                  "    \"decision\": {\"FASTER\"}\n"
                  "\n"
                  "Another example:\n"
                  "Final Answer:\n"
                  "    \"decision\": {\"IDLE\"}\n"
                  "\n"
                  "IMPORTANT: Only output the Final Answer in the exact format above. Do NOT add any explanation, thinking, or extra text.\n")
        completion = client.chat.completions.create(
            model=SILICONFLOW_MODEL,  # 硅基流动的 Qwen2.5-7B-Instruct
            messages=[
                {"role": "system", "content": "You are an expert driving decision assistant. Follow the user's instructions and output format exactly."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,  # 让输出更确定，格式更稳定
        )

        llm_response = completion.choices[0].message
        decision_content = llm_response.content
        llm_suggested_action = self.extract_decision(decision_content)
        print(f"llm action: {llm_suggested_action}")

        llm_action_id = self.get_action_id_from_name(llm_suggested_action, self.ACTIONS_ALL)
        llm_action = np.array([llm_action_id])
        return llm_action, coverage_signal, topk_actions, library_size

    def reset(self, **kwargs):
        obs = self.env.reset(**kwargs)
        return obs  # Make sure to return the observation

    def get_available_actions(self):
        """Get the list of available actions from the underlying Highway environment."""
        if hasattr(self.env, 'get_available_actions'):
            return self.env.get_available_actions()
        else:
            raise NotImplementedError(
                "The method get_available_actions is not implemented in the underlying environment.")

    def extract_decision(self, response_content):
        """鲁棒地从 LLM 输出中提取决策 action。
        解析失败时 fallback 到 IDLE（最安全动作），避免程序崩溃。
        """
        try:
            decision = None
            # 策略 1: 标准格式 "decision": {"FASTER"}
            if '"decision"' in response_content:
                start = response_content.find('"decision"')
                brace_start = response_content.find('{', start)
                if brace_start != -1:
                    brace_end = response_content.find('}', brace_start)
                    if brace_end != -1:
                        decision = response_content[brace_start + 1:brace_end].strip().strip('"').strip("'")

            # 策略 2: 全文搜 action 关键字（兼容 Qwen 等模型格式不稳定）
            if not decision or not any(a in decision.upper() for a in ['FASTER', 'SLOWER', 'LANE_LEFT', 'LANE_RIGHT', 'IDLE']):
                upper = response_content.upper()
                for action in ['FASTER', 'SLOWER', 'LANE_LEFT', 'LANE_RIGHT', 'IDLE']:
                    if action in upper:
                        decision = action
                        break

            # 策略 3: 标准化到合法 action
            if self.is_intersection:
                if decision and "FASTER" in decision.upper():
                    return "FASTER"
                elif decision and "SLOWER" in decision.upper():
                    return "SLOWER"
                elif decision and "IDLE" in decision.upper():
                    return "IDLE"
            else:
                if decision and "LANE_LEFT" in decision.upper():
                    return "LANE_LEFT"
                elif decision and "LANE_RIGHT" in decision.upper():
                    return "LANE_RIGHT"
                elif decision and "FASTER" in decision.upper():
                    return "FASTER"
                elif decision and "SLOWER" in decision.upper():
                    return "SLOWER"
                elif decision and "IDLE" in decision.upper():
                    return "IDLE"

            # 全部失败：fallback 到 IDLE
            self.parse_failures += 1
            print(f"无法解析 LLM 输出: {response_content[:100]!r}，fallback 到 IDLE")
            return "IDLE"
        except Exception as e:
            self.parse_failures += 1
            print(f"Error in extracting decision: {e}，fallback 到 IDLE")
            return "IDLE"

    def prompt_engineer(self,  ego_veh, road, env, negotiation_results, conflicting_info, n_vehicles=None):
        # self.sce.updateVehicles(obs, frame, i)
        # Observation translation
        msg0 = available_action(self.toolModels, ego_veh, road, env, is_intersection=self.is_intersection)
        availabel_lane, msg1 = get_available_lanes(self.toolModels, ego_veh, road, env)
        msg2, lane_cars_id = get_involved_cars(self.toolModels, ego_veh, road, env, availabel_lane)
        #lane_cars_id -- {'lane_0': {'leadingCar': None, 'rearingCar': IDMVehicle #224: [173.94198546   0.        ]}}
        #availabel_lane -- {'currentLaneID': 'lane_0', 'leftLane': '', 'rightLane': ''}

        #msg1_info = next(iter(msg1.values()))
        # lanes_info = extract_lanes_info(msg1_info) #{'current': 'lane_3', 'left': 'lane_2', 'right': None}

        # lane_car_ids = extract_lane_and_car_ids(lanes_info, msg2) #{'current_lane': {'car_id': 'veh1', 'lane_id': 'lane_3'}, 'left_lane': {'car_id': 'veh3', 'lane_id': 'lane_2'}, 'right_lane': {'car_id': None, 'lane_id': None}}
        if availabel_lane["leftLane"] != "" or availabel_lane["rightLane"] != "":  # 如果需要换道
            safety_assessment = assess_lane_change_safety(self.toolModels, lane_cars_id, availabel_lane, ego_veh) #{'left_lane_change_safe': True, 'right_lane_change_safe': True}
        else:
            safety_assessment = "There is no need to assess lane change safety."
        safety_msg = check_safety_in_current_lane(self.toolModels, lane_cars_id, availabel_lane, ego_veh) #{'acceleration_conflict': 'acceleration may be conflict with `veh1`, which is unacceptable.', 'keep_speed_conflict': 'keep lane with current speed may be conflict with veh1, you need consider decelerate', 'deceleration_conflict': 'deceleration with current speed is safe with veh1'}
        safety_msg2, most_dangerous_info = check_safety_with_conflict_vehicles(ego_veh, negotiation_results, conflicting_info, env)
        prompt_info = format_training_info(msg0, msg1, msg2, availabel_lane, lane_cars_id, safety_assessment, safety_msg, safety_msg2, most_dangerous_info)  # msg0, msg2, availabel_lane, safety_assessment, safety_msg
        # ===== 方向D：签名独立构造（改动清单 #2），prompt_info 逐字不变 =====
        # 原签名 = prompt_info 最后一行，与 memory_update 的 orig 分支、原论文实现完全一致
        signature_orig = prompt_info.strip().split('\n')[-1]
        # 冲突方位只算一次，签名与日志共用
        conflict_direction = conflict_direction_label(
            ego_veh, select_conflicting_vehicle(ego_veh, negotiation_results, conflicting_info, env))
        signature_new, relation, delta_speed = build_memory_signature(
            ego_veh, env, conflicting_info, negotiation_results, most_dangerous_info,
            n_vehicles=n_vehicles, conflict_direction=conflict_direction)
        sig_info = {
            'signature_orig': signature_orig,       # 离线算 orig 的 AUROC
            'signature_new': signature_new,         # 离线算 new 的 AUROC
            'relation': relation,
            'delta_speed': delta_speed,
            'n_conflicts': len(conflicting_info) if conflicting_info else 0,
            'conflict_direction': conflict_direction if relation is not None else None,
            'dangerous_level': most_dangerous_info.get('dangerous_level', 0),
        }
        return prompt_info, sig_info

    def extract_vehicle_conflicts(self, prompt: str, vehicle_id: str) -> list:
        pattern = re.compile(r'"first_vehicle": "(MDPVehicle #[0-9]+|IDMVehicle #[0-9]+)", "second_vehicle": "(MDPVehicle #[0-9]+|IDMVehicle #[0-9]+)"')
        conflicts = pattern.findall(prompt)

        vehicle_conflicts = []
        for first, second in conflicts:
            if first == vehicle_id:
                vehicle_conflicts.append((first, second, 'first'))
            elif second == vehicle_id:
                vehicle_conflicts.append((first, second, 'second'))
        return vehicle_conflicts
