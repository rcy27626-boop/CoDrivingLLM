import argparse
import json
import os
import re
import time

import gym
import imageio
import openpyxl

import highway_env
from llm_controller.llm_agent_action import LlmAgent_action_module
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
    args = parser.parse_args()

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
        mem_dir = os.path.join("llm_controller", "seed_memory", args.scene)
        os.makedirs(mem_dir, exist_ok=True)
        os.environ["MEMORY_DB_DIR"] = mem_dir

    total_start = time.time()
    for i in range(args.start, args.start + args.n):
        print("=" * 70)
        print(f"[{time.strftime('%H:%M:%S')}] scene={args.scene} method={args.method} episode#{i} (seed={args.seed + i})")
        round_start = time.time()

        # 单轮错误隔离：某轮崩溃不中断整个批次，记录失败后继续下一轮
        try:
            # 视频录制（默认开启，--no-video 时关闭）
            writer = None
            if not args.no_video:
                video_path = os.path.join(video_dir, str(i) + ".mp4")
                writer = imageio.get_writer(video_path, fps=30)

            file_name, workbook = open_excel(out_dir, i)

            # 每轮独立记忆对象（2shot/5shot 时用于检索；0shot/no-negotiation 用 None）
            # --memory-update 建库时也需要记忆对象（写入用）
            memory = DrivingMemory(env) if (use_memory or args.memory_update) else None

            terminated = False
            t = 0
            # 本仓库的 highway_env 是旧版 API：reset(is_training, testing_seeds)。
            # 用 testing mode 显式指定种子，可同时固定 numpy.random 和 random，
            # 并避免调用被实例属性遮蔽的 env.seed() 方法。
            obs = env.reset(is_training=False, testing_seeds=args.seed + i)
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
                llm_actions = llm_agent.llm_controller_run(
                    env, negotiation_prompt, conflicting_info,
                    env.controlled_vehicles, memory,
                    use_memory=use_memory, memory_top_k=memory_top_k,
                    memory_update=args.memory_update)
                llm_calls += len(llm_actions)
                episode_parse_failures += llm_agent.parse_failures

                action = [item for sublist in llm_actions for item in sublist]

                obs, global_reward, terminated, info = env.step(tuple(action), env)

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
