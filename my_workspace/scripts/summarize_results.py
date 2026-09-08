#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CoDrivingLLM 实验结果汇总脚本

遍历 result/<batch>/ 下所有 progress.json，统计每格指标，
输出 Markdown 汇总表 + CSV 文件，并与作者基准数据对比。

用法：
    python summarize_results.py --batch 20260905_full
    python summarize_results.py --batch 20260905_full --output report.md
"""

import argparse
import json
import os
import sys
from collections import defaultdict


# 作者基准数据（从 videos&data 目录后缀推断，论文 Table I 部分确认）
AUTHOR_BASELINE = {
    "intersection": {
        "0shot": {"success_rate": 0.74, "note": "目录后缀 74"},
        "2shot": {"success_rate": 0.90, "note": "论文 Table I 确认"},
        "5shot": {"success_rate": 0.80, "note": "目录后缀 80"},
        "no-negotiation": {"success_rate": 0.15, "note": "目录后缀 15，论文消融确认"},
    },
    "merge": {
        "0shot": {"success_rate": 0.75, "note": "目录后缀 75"},
        "2shot": {"success_rate": 0.85, "note": "目录后缀 85"},
        "5shot": {"success_rate": 0.84, "note": "目录后缀 84"},
        "no-negotiation": {"success_rate": 0.33, "note": "目录后缀 33"},
    },
}

METHOD_ORDER = ["0shot", "no-negotiation", "2shot", "5shot"]
SCENE_ORDER = ["intersection", "merge", "highway"]


def load_progress(progress_path):
    """加载 progress.json，返回轮次记录列表。"""
    if not os.path.exists(progress_path):
        return []
    with open(progress_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 按 round 排序
    records = sorted(data.values(), key=lambda x: x.get("round", 0))
    return records


def calc_metrics(records):
    """从轮次记录计算统计指标。"""
    if not records:
        return None

    # 区分正常完成和崩溃的轮次
    valid = [r for r in records if "error" not in r]
    crashed = [r for r in records if "error" in r]

    total = len(valid)
    if total == 0:
        return {"total": 0, "crashed_episodes": len(crashed)}

    success = sum(1 for r in valid if r.get("success", False))
    num_crashed_total = sum(r.get("num_crashed", 0) for r in valid)
    num_arrived_total = sum(r.get("num_arrived", 0) for r in valid)
    num_cav_total = sum(r.get("num_cav", 0) for r in valid)
    timeout = sum(1 for r in valid if r.get("timeout", False))
    collision_episodes = sum(1 for r in valid if r.get("num_crashed", 0) > 0)

    speeds = [r.get("avg_speed", 0) for r in valid if r.get("avg_speed", 0) > 0]
    steps = [r.get("total_steps", 0) for r in valid if r.get("total_steps", 0) > 0]
    llm_calls = [r.get("llm_calls", 0) for r in valid if r.get("llm_calls", 0) > 0]
    parse_failures = [r.get("parse_failures", 0) for r in valid]
    durations = [r.get("duration_seconds", 0) for r in valid if r.get("duration_seconds", 0) > 0]

    def avg(lst):
        return round(sum(lst) / len(lst), 2) if lst else 0

    return {
        "total": total,
        "crashed_episodes": len(crashed),
        "success_count": success,
        "success_rate": round(success / total, 4),
        "collision_rate": round(collision_episodes / total, 4),
        "timeout_rate": round(timeout / total, 4),
        "vehicle_arrival_rate": round(num_arrived_total / num_cav_total, 4) if num_cav_total > 0 else 0,
        "avg_speed": avg(speeds),
        "avg_steps": avg(steps),
        "avg_llm_calls": avg(llm_calls),
        "avg_parse_failures": avg(parse_failures),
        "avg_duration_min": round(avg(durations) / 60, 2) if durations else 0,
    }


def scan_results(result_root, batch):
    """扫描 result/<batch>/ 下所有格子。"""
    batch_dir = os.path.join(result_root, batch)
    if not os.path.exists(batch_dir):
        print(f"[错误] 批次目录不存在: {batch_dir}")
        sys.exit(1)

    results = defaultdict(dict)  # results[scene][method] = metrics

    for scene in os.listdir(batch_dir):
        scene_path = os.path.join(batch_dir, scene)
        if not os.path.isdir(scene_path):
            continue
        for method in os.listdir(scene_path):
            method_path = os.path.join(scene_path, method)
            if not os.path.isdir(method_path):
                continue
            progress_path = os.path.join(method_path, "progress.json")
            records = load_progress(progress_path)
            if records:
                metrics = calc_metrics(records)
                results[scene][method] = metrics

    return results


def generate_markdown(results, batch):
    """生成 Markdown 汇总报告。"""
    lines = []
    lines.append(f"# CoDrivingLLM 实验汇总报告")
    lines.append(f"")
    lines.append(f"**批次**: `{batch}`")
    lines.append(f"**生成时间**: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"")

    # 按场景输出
    for scene in SCENE_ORDER:
        if scene not in results:
            continue
        lines.append(f"## {scene}")
        lines.append(f"")

        # 表头
        lines.append(f"| 方法 | 轮次 | 成功率 | 碰撞率 | 超时率 | 车辆到达率 | 平均速度(m/s) | 平均步数 | 平均LLM调用 | 平均耗时(min) | 作者基准 | 差异 |")
        lines.append(f"|------|------|--------|--------|--------|-----------|--------------|---------|------------|-------------|---------|------|")

        for method in METHOD_ORDER:
            if method not in results[scene]:
                continue
            m = results[scene][method]
            if m["total"] == 0:
                continue

            author = AUTHOR_BASELINE.get(scene, {}).get(method, {})
            author_rate = author.get("success_rate", None)
            author_note = author.get("note", "-")

            if author_rate is not None:
                diff = m["success_rate"] - author_rate
                diff_str = f"{diff:+.2%}"
                author_str = f"{author_rate:.0%} ({author_note})"
            else:
                diff_str = "-"
                author_str = "-"

            lines.append(
                f"| {method} "
                f"| {m['total']} "
                f"| {m['success_rate']:.1%} "
                f"| {m['collision_rate']:.1%} "
                f"| {m['timeout_rate']:.1%} "
                f"| {m['vehicle_arrival_rate']:.1%} "
                f"| {m['avg_speed']} "
                f"| {m['avg_steps']} "
                f"| {m['avg_llm_calls']} "
                f"| {m['avg_duration_min']} "
                f"| {author_str} "
                f"| {diff_str} |"
            )

        lines.append(f"")

    # 详细指标
    lines.append(f"## 详细指标")
    lines.append(f"")
    for scene in sorted(results.keys()):
        for method in sorted(results[scene].keys()):
            m = results[scene][method]
            if m["total"] == 0:
                continue
            lines.append(f"### {scene} / {method}")
            lines.append(f"- 有效轮次: {m['total']}" + (f"（崩溃 {m['crashed_episodes']} 轮）" if m['crashed_episodes'] > 0 else ""))
            lines.append(f"- 成功: {m['success_count']}/{m['total']} = {m['success_rate']:.1%}")
            lines.append(f"- 碰撞轮次: {m['collision_rate']:.1%}")
            lines.append(f"- 超时轮次: {m['timeout_rate']:.1%}")
            lines.append(f"- 车辆到达率: {m['vehicle_arrival_rate']:.1%}")
            lines.append(f"- 平均速度: {m['avg_speed']} m/s")
            lines.append(f"- 平均步数: {m['avg_steps']}")
            lines.append(f"- 平均 LLM 调用: {m['avg_llm_calls']} 次/轮")
            lines.append(f"- 平均解析失败: {m['avg_parse_failures']} 次/轮")
            lines.append(f"- 平均耗时: {m['avg_duration_min']} min/轮")
            lines.append(f"")

    # 结论
    lines.append(f"## 关键结论")
    lines.append(f"")
    for scene in sorted(results.keys()):
        if scene not in results:
            continue
        methods_data = results[scene]
        if "0shot" in methods_data and "2shot" in methods_data:
            s0 = methods_data["0shot"]["success_rate"]
            s2 = methods_data["2shot"]["success_rate"]
            lines.append(f"- **{scene}**: 2shot ({s2:.1%}) vs 0shot ({s0:.1%})，记忆提升 {(s2-s0):+.1%}")
        if "0shot" in methods_data and "no-negotiation" in methods_data:
            s0 = methods_data["0shot"]["success_rate"]
            sn = methods_data["no-negotiation"]["success_rate"]
            lines.append(f"- **{scene}**: 有协商 ({s0:.1%}) vs 无协商 ({sn:.1%})，协商提升 {(s0-sn):+.1%}")

    return "\n".join(lines)


def generate_csv(results, batch, output_path):
    """生成 CSV 汇总文件。"""
    import csv
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "scene", "method", "total_rounds", "crashed_rounds",
            "success_count", "success_rate", "collision_rate", "timeout_rate",
            "vehicle_arrival_rate", "avg_speed", "avg_steps",
            "avg_llm_calls", "avg_parse_failures", "avg_duration_min",
            "author_success_rate", "diff_vs_author"
        ])
        for scene in sorted(results.keys()):
            for method in METHOD_ORDER:
                if method not in results[scene]:
                    continue
                m = results[scene][method]
                if m["total"] == 0:
                    continue
                author = AUTHOR_BASELINE.get(scene, {}).get(method, {})
                author_rate = author.get("success_rate", "")
                diff = f"{m['success_rate'] - author_rate:.4f}" if author_rate != "" else ""
                writer.writerow([
                    scene, method, m["total"], m["crashed_episodes"],
                    m["success_count"], f"{m['success_rate']:.4f}",
                    f"{m['collision_rate']:.4f}", f"{m['timeout_rate']:.4f}",
                    f"{m['vehicle_arrival_rate']:.4f}", m["avg_speed"],
                    m["avg_steps"], m["avg_llm_calls"],
                    m["avg_parse_failures"], m["avg_duration_min"],
                    author_rate, diff
                ])
    print(f"[CSV] 已保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="CoDrivingLLM 实验结果汇总")
    parser.add_argument("--batch", default="20260905_full", help="实验批次名")
    parser.add_argument("--result-root", default="llm_controller/result", help="结果根目录")
    parser.add_argument("--output", default=None, help="Markdown 输出路径（默认打印到终端）")
    parser.add_argument("--csv", default=None, help="CSV 输出路径（默认 <batch>_summary.csv）")
    args = parser.parse_args()

    print(f"扫描批次: {args.batch}")
    results = scan_results(args.result_root, args.batch)

    total_cells = sum(len(v) for v in results.values())
    total_rounds = sum(m["total"] for scene in results.values() for m in scene.values())
    print(f"找到 {total_cells} 个格子，共 {total_rounds} 轮有效数据")

    md = generate_markdown(results, args.batch)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"[Markdown] 已保存: {args.output}")
    else:
        print("\n" + md)

    csv_path = args.csv or f"{args.batch}_summary.csv"
    generate_csv(results, args.batch, csv_path)


if __name__ == "__main__":
    main()
