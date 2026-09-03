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
                        help="输出根目录，默认 ./llm_controller/result/<scene>/<method>")
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

    # 输出目录：result/<scene>/<method>/{data, video, progress.json, db}
    root = args.output_dir or os.path.join("llm_controller", "result")
    out_dir = os.path.join(root, args.scene, args.method, "data")
    video_dir = os.path.join(root, args.scene, args.method, "video")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(video_dir, exist_ok=True)
    progress_path = os.path.join(root, args.scene, args.method, "progress.json")
    records = load_progress(progress_path)

    # few-shot 方法使用独立记忆库（0shot / no-negotiation 不创建，避免无谓的嵌入网络调用）
    if use_memory:
        mem_dir = os.path.join(root, args.scene, args.method, "db")
        os.environ["MEMORY_DB_DIR"] = mem_dir

    total_start = time.time()
    for i in range(args.start, args.start + args.n):
        print("=" * 70)
        print(f"[{time.strftime('%H:%M:%S')}] scene={args.scene} method={args.method} episode#{i}")
        round_start = time.time()

        video_path = os.path.join(video_dir, str(i) + ".mp4")
        writer = imageio.get_writer(video_path, fps=30)

        file_name, workbook = open_excel(out_dir, i)

        # 每轮独立记忆对象（2shot/5shot 时用于检索；0shot/no-negotiation 用 None）
        memory = DrivingMemory(env) if use_memory else None

        terminated = False
        t = 0
        obs = env.reset()
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
                use_memory=use_memory, memory_top_k=memory_top_k)
            llm_calls += len(llm_actions)
            episode_parse_failures += llm_agent.parse_failures

            action = [item for sublist in llm_actions for item in sublist]

            obs, global_reward, terminated, info = env.step(tuple(action), env)

            frame = env.render("rgb_array")
            writer.append_data(frame)

            workbook = write_data(workbook, env, t)
            workbook.save(file_name)
            t += 1

        writer.close()

        summary, avg_speed = episode_summary(env)
        round_dur = round(time.time() - round_start, 1)
        # 成功判定：未碰撞；intersection/merge 还需至少一辆车到达；highway 时间跑完即成功
        success = (summary["num_crashed"] == 0) and (
            (summary["num_arrived"] >= 1) if get_scene_name(env) in ("intersection", "merge")
            else True
        )
        timeout = summary["num_arrived"] == 0 and summary["num_crashed"] == 0

        record = {
            "round": i,
            "scene": args.scene,
            "method": args.method,
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
        print(f"[episode#{i} done] {record}")

    total_dur = round(time.time() - total_start, 1)
    print("=" * 70)
    print(f"全部完成: {args.scene}/{args.method} episodes {args.start}~{args.start + args.n - 1}, 总耗时 {total_dur}s")


if __name__ == "__main__":
    main()