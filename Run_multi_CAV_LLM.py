import argparse
import json
import os
import re
import time

import gym
import imageio
import openpyxl

import highway_env
from llm_controller.llm_agent_action import LlmAgent_action_module, MEMORY_MIN_LIBRARY_SIZE
from llm_controller.llm_agent_negotiation_system import LlmAgent_negotiation_module
from llm_controller.memory import DrivingMemory


def open_excel(file_dir, i):
    """创建/打开第 i 轮的 Excel 工作簿（断点续跑时保留旧数据）。"""
    if not os.path.exists(file_dir):
        os.makedirs(file_dir)
    file_name = os.path.join(file_dir, str(i) + ".xlsx")
    workbook = openpyxl.Workbook()
    if os.path.exists(file_name):
        workbook = openpyxl.load_workbook(file_name)
    return file_name, workbook


def write_data(workbook, env, t):
    column_names = ["t", "x", "y", "v", "theta", "background_veh?"]
    for vehicle in env.road.vehicles:
        sheet_name = str(vehicle.id)
        if sheet_name not in workbook.sheetnames:
            worksheet = workbook.create_sheet(sheet_name)
            worksheet.append(column_names)
        else:
            worksheet = workbook[sheet_name]
        controlled_vehicles = env.controlled_vehicles
        background_vehicles = vehicle not in controlled_vehicles
        state = [
            round(vehicle.position[0], 2),
            round(vehicle.position[1], 2),
            round(vehicle.speed, 2),
            round(vehicle.heading, 2),
            background_vehicles,
        ]
        row_data = [t] + state
        worksheet.append(row_data)
        worksheet.cell(row=t + 2, column=1, value=t)
        for j, item in enumerate(state):
            worksheet.cell(row=t + 2, column=j + 2, value=item)
    return workbook


def get_scene_name(env):
    match = re.search(r"(merge|intersection|highway)", env.spec.id)
    return match.group(0) if match else "unknown"


def has_arrived(env, vehicle):
    """兼容各环境的到达判定（highway 没有该方法时返回 False）。"""
    has_arrived_method = getattr(env.unwrapped, "has_arrived", None)
    if has_arrived_method is not None:
        try:
            return bool(has_arrived_method(vehicle))
        except Exception:
            return False
    return False


def episode_summary(env):
    """收集本轮结束后的核心指标。"""
    vehicles = env.controlled_vehicles
    num_cav = len(vehicles)
    num_crashed = sum(1 for v in vehicles if v.crashed)
    num_arrived = sum(1 for v in vehicles if has_arrived(env, v))
    speeds = [v.speed for v in vehicles if not v.crashed]
    avg_speed = round(sum(speeds) / len(speeds), 2) if speeds else 0.0
    return {
        "num_cav": num_cav,
        "num_crashed": num_crashed,
        "num_arrived": num_arrived,
    }, avg_speed


def load_progress(progress_path):
    if os.path.exists(progress_path):
        with open(progress_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(progress_path, records):
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="CoDrivingLLM 实验运行器")
    parser.add_argument("--scene", default="intersection",
                        choices=["intersection", "merge", "highway"],
                        help="仿真场景")
    parser.add_argument("--method", default="0shot",
                        choices=["0shot", "2shot", "5shot", "no-negotiation"],
                        help="决策方法：0shot=无记忆，2shot/5shot=few-shot 记忆，no-negotiation=无协商")
    parser.add_argument("--n", type=int, default=10,
                        help="本轮要跑的总轮次（从 start 到 start+n-1）")
    parser.add_argument("--start", type=int, default=0,
                        help="起始轮次（断点续跑）")
    parser.add_argument("--output_dir", default=None,
                        help="输出根目录，默认 ./llm_controller/result/<batch>/<scene>/<method>")
    parser.add_argument("--seed", type=int, default=42,
                        help="基础随机种子，第 i 轮用 seed+i（保证不同方法看到相同初始场景）")
    parser.add_argument("--no-video", action="store_true", default=False,
                        help="关闭视频录制（默认录视频；加此开关则不录，加速实验）")
    parser.add_argument("--memory-update", action="store_true", default=False,
                        help="是否将每步决策写入记忆库（用于建种子库，默认关闭）")
    parser.add_argument("--strict-success", action="store_true", default=True,
                        help="成功判定用论文口径：所有CAV都安全到达（默认开启）；关闭则至少1辆到达")
    parser.add_argument("--batch", default="default",
                        help="实验批次名称，隔离输出目录（如 20260903_smoke / 20260905_full）")
    # ===== 方向D（覆盖度感知记忆签名）新增参数 =====
    parser.add_argument("--memory-signature", default="orig", choices=["orig", "new"],
                        help="记忆签名类型：orig=论文原签名（prompt_info 最后一行）；new=覆盖度感知签名（方向D 新增）")
    parser.add_argument("--coverage-guard", action="store_true", default=False,
                        help="启用覆盖度降级干预（需配合 --th-a/--th-b；与 --memory-update 互斥）")
    parser.add_argument("--th-a", type=float, default=None,
                        help="覆盖度阈值 th_a：coverage_signal <= th_a 视为熟（不偏置）")
    parser.add_argument("--th-b", type=float, default=None,
                        help="覆盖度阈值 th_b：coverage_signal > th_b 视为很生（偏置 2 档）")
    parser.add_argument("--initial-vehicle-count", type=int, default=10,
                        help="reset 时的初始车辆数：ID 用 10，OOD 高密度用 40~60（仅 intersection 生效）")
    parser.add_argument("--spawn-probability", type=float, default=0.6,
                        help="随机车辆生成概率（仅 intersection 生效，默认 0.6 与改动前一致；调高可加密度）")
    parser.add_argument("--split", default=None,
                        help="实验标识：只决定 step_logs 文件名；默认 v{initial_vehicle_count}_{memory_signature}")
    parser.add_argument("--memory-db-dir", default=None,
                        help="记忆库根目录（决定读写哪个库）；默认 seed_memory/<scene>/<split>，实际落盘再加一层 <env_id>")
    args = parser.parse_args()

    # split 只决定日志文件名，不改结果目录结构（设计稿 v3-11 / v3-19）
    if args.split is None:
        args.split = f"v{args.initial_vehicle_count}_{args.memory_signature}"

    # 参数校验（设计稿 §6.3）
    if args.coverage_guard and args.memory_update:
        parser.error("--coverage-guard 与 --memory-update 互斥：建库必须是纯策略行为，实验必须冻结库")
    if args.coverage_guard and (args.th_a is None or args.th_b is None):
        parser.error("--coverage-guard 需要 --th-a 与 --th-b（先用冻结库做 leave-one-out 标定）")
    if args.coverage_guard and args.scene == "highway":
        parser.error("--coverage-guard 只在 intersection / merge 场景启用（highway 动作空间含换道，本次不做）")

    # few-shot 参数
    memory_top_k = 2
    use_memory = False
    if args.method == "2shot":
        use_memory, memory_top_k = True, 2
    elif args.method == "5shot":
        use_memory, memory_top_k = True, 5
    use_negotiation = args.method != "no-negotiation"

    # 环境
    env_id = {"intersection": "intersection-multi-agent-v0",
              "merge": "merge-multi-agent-v0",
              "highway": "highway-v0"}[args.scene]
    env = gym.make(env_id)

    # 按命令行覆盖场景参数（OOD 密度旋钮）
    # initial_vehicle_count 在每次 _reset() 里被读取，这里更新即生效；
    # spawn_probability 由 intersection_env.py 的 _make_vehicles 传入才生效（默认 0.6 与改动前一致）。
    # 用 unwrapped 访问真实环境实例：gym 不同版本 make() 可能返回包装器，
    # 包装器虽然会转发属性，但 unwrapped 在任何版本都指向底层 env，更稳。
    env.unwrapped.config.update({
        "initial_vehicle_count": args.initial_vehicle_count,
        "spawn_probability": args.spawn_probability,
    })

    # 输出目录：result/<batch>/<scene>/<method>/{data, video, progress.json}
    root = args.output_dir or os.path.join("llm_controller", "result", args.batch)
    out_dir = os.path.join(root, args.scene, args.method, "data")
    video_dir = os.path.join(root, args.scene, args.method, "video")
    os.makedirs(out_dir, exist_ok=True)
    if not args.no_video:
        os.makedirs(video_dir, exist_ok=True)
    progress_path = os.path.join(root, args.scene, args.method, "progress.json")
    records = load_progress(progress_path)

    # 2shot/5shot 共享同一场景的种子记忆库（放在固定位置，不随 batch/method 隔离）
    # 0shot/no-negotiation 不创建记忆对象，但 --memory-update 建库时也需要路径
    if use_memory or args.memory_update:
        # 库路径与日志 split 分离（设计稿 v3-20）：库路径由 --memory-db-dir 决定
        mem_dir = args.memory_db_dir or os.path.join("llm_controller", "seed_memory", args.scene, args.split)
        os.makedirs(mem_dir, exist_ok=True)
        os.environ["MEMORY_DB_DIR"] = mem_dir
        print(f"[memory] MEMORY_DB_DIR = {mem_dir}（实际落盘 {os.path.join(mem_dir, env_id)}）")

    total_start = time.time()
    for i in range(args.start, args.start + args.n):
        print("=" * 70)
        print(f"[{time.strftime('%H:%M:%S')}] scene={args.scene} method={args.method} episode#{i} (seed={args.seed + i})")
        round_start = time.time()

        # 单轮错误隔离：某轮崩溃不中断整个批次，记录失败后继续下一轮
        try:
            # 视频录制（默认开启，--no-video 时关闭）
            writer = None
            step_log_f = None
            if not args.no_video:
                video_path = os.path.join(video_dir, str(i) + ".mp4")
                writer = imageio.get_writer(video_path, fps=30)

            file_name, workbook = open_excel(out_dir, i)

            # 每步决策日志（离线迭代的唯一数据源，设计稿 §5）：每集一个文件，文件名带 split 与轮次号
            step_log_path = os.path.join(out_dir, f"step_logs_{args.split}_ep{i}.jsonl")
            step_log_f = open(step_log_path, "w", encoding="utf-8")

            # 每轮独立记忆对象（2shot/5shot 时用于检索；0shot/no-negotiation 用 None）
            # --memory-update 建库时也需要记忆对象（写入用）
            memory = DrivingMemory(env) if (use_memory or args.memory_update) else None
            if use_memory and memory is not None:
                lib_size = memory.memory_size()
                if lib_size < MEMORY_MIN_LIBRARY_SIZE:
                    print(f"[warn] 记忆库条目数 {lib_size} < {MEMORY_MIN_LIBRARY_SIZE}：本集不产生 coverage_signal（不触发降级）")

            terminated = False
            t = 0
            # 本仓库的 highway_env 是旧版 API：reset(is_training, testing_seeds)。
            # 用 testing mode 显式指定种子，可同时固定 numpy.random 和 random，
            # 并避免调用被实例属性遮蔽的 env.seed() 方法。
            obs = env.reset(is_training=False, testing_seeds=args.seed + i)
            n_vehicles_fixed = len(env.road.vehicles)  # 签名用的车数：reset 后固定、整集不变（设计稿 v3-15）
            llm_calls = 0
            episode_parse_failures = 0

            while not terminated:
                print("-" * 70)
                # 协商模块（no-negotiation 时跳过真正的 LLM 调用）
                llm_agent_conflict_resolver = LlmAgent_negotiation_module(env)
                if use_negotiation:
                    negotiation_prompt, conflicting_info = llm_agent_conflict_resolver.llm_controller_run(env)
                    llm_calls += 1
                else:
                    negotiation_prompt, conflicting_info = "", []

                # 决策
                llm_agent = LlmAgent_action_module(env)
                llm_actions, step_records = llm_agent.llm_controller_run(
                    env, negotiation_prompt, conflicting_info,
                    env.controlled_vehicles, memory,
                    use_memory=use_memory, memory_top_k=memory_top_k,
                    memory_update=args.memory_update,
                    memory_signature_kind=args.memory_signature,
                    coverage_guard=args.coverage_guard,
                    th_a=args.th_a, th_b=args.th_b,
                    log_ctx={"episode": i, "step": t, "split": args.split},
                    n_vehicles_fixed=n_vehicles_fixed)
                llm_calls += len(llm_actions)
                episode_parse_failures += llm_agent.parse_failures

                action = [item for sublist in llm_actions for item in sublist]

                obs, global_reward, terminated, info = env.step(tuple(action), env)

                # step 之后才能补上 crashed/terminated/arrived（设计稿 §5.1 / v3-4）
                veh_by_id = {str(vehicle): vehicle for vehicle in env.controlled_vehicles}
                for step_record in step_records:
                    step_veh = veh_by_id.get(step_record.get('vehicle_id'))
                    step_record['crashed_after'] = bool(step_veh.crashed) if step_veh is not None else None
                    step_record['arrived_after'] = bool(has_arrived(env, step_veh)) if step_veh is not None else None
                    step_record['terminated_after'] = bool(terminated)
                    step_log_f.write(json.dumps(step_record, ensure_ascii=False) + "\n")
                step_log_f.flush()

                if not args.no_video and writer is not None:
                    frame = env.render("rgb_array")
                    writer.append_data(frame)

                workbook = write_data(workbook, env, t)
                workbook.save(file_name)
                t += 1

            # 每集结束强制落盘，避免最后不足一个 batch 的记忆只停留在内存中。
            if memory is not None:
                memory.flush()

            if writer is not None:
                writer.close()

            if step_log_f is not None:
                step_log_f.close()

            summary, avg_speed = episode_summary(env)
            round_dur = round(time.time() - round_start, 1)

            # 成功判定
            scene_name = get_scene_name(env)
            if args.strict_success and scene_name in ("intersection", "merge"):
                # 论文口径：所有 CAV 都安全到达且无碰撞
                success = (summary["num_crashed"] == 0) and (summary["num_arrived"] == summary["num_cav"])
            elif scene_name in ("intersection", "merge"):
                # 宽松口径：无碰撞且至少 1 辆到达
                success = (summary["num_crashed"] == 0) and (summary["num_arrived"] >= 1)
            else:
                # highway：无碰撞即成功（该环境无 has_arrived）
                success = summary["num_crashed"] == 0
            # 超时：无碰撞但未全部到达（intersection/merge）
            timeout = (scene_name in ("intersection", "merge")) and \
                      (summary["num_crashed"] == 0) and \
                      (summary["num_arrived"] < summary["num_cav"])

            record = {
                "round": i,
                "scene": args.scene,
                "method": args.method,
                "seed": args.seed + i,
                "success": success,
                "num_cav": summary["num_cav"],
                "num_arrived": summary["num_arrived"],
                "num_crashed": summary["num_crashed"],
                "timeout": timeout,
                "avg_speed": avg_speed,
                "total_steps": t,
                "llm_calls": llm_calls,
                "parse_failures": episode_parse_failures,
                "duration_seconds": round_dur,
            }
            records[str(i)] = record
            save_progress(progress_path, records)
            print(f"[episode#{i} done] success={success} crashed={summary['num_crashed']}/{summary['num_cav']} arrived={summary['num_arrived']}/{summary['num_cav']} steps={t} llm_calls={llm_calls} dur={round_dur}s")

        except Exception as e:
            # 单轮崩溃：记录失败，关闭 writer，继续下一轮
            round_dur = round(time.time() - round_start, 1)
            print(f"[episode#{i} 崩溃] {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            if 'writer' in dir() and writer is not None:
                try:
                    writer.close()
                except Exception:
                    pass
            if locals().get('step_log_f') is not None:
                try:
                    step_log_f.close()
                except Exception:
                    pass
            # 异常退出时尽量保存已缓存的记忆，flush 自身会捕获写入异常。
            if 'memory' in locals() and memory is not None:
                memory.flush()
            record = {
                "round": i,
                "scene": args.scene,
                "method": args.method,
                "seed": args.seed + i,
                "success": False,
                "error": f"{type(e).__name__}: {str(e)[:200]}",
                "duration_seconds": round_dur,
            }
            records[str(i)] = record
            save_progress(progress_path, records)
            continue

    total_dur = round(time.time() - total_start, 1)
    print("=" * 70)
    print(f"全部完成: {args.scene}/{args.method} episodes {args.start}~{args.start + args.n - 1}, 总耗时 {total_dur}s")


if __name__ == "__main__":
    main()
