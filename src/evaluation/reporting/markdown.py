from __future__ import annotations

"""Markdown 评测报告生成器 —— 确定性、不依赖 LLM。"""

import json
from pathlib import Path


def _load(run_dir: Path, name: str, default):
    p = run_dir / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def generate_markdown_report(run_dir: str | Path) -> Path:
    run_dir = Path(run_dir)
    config = _load(run_dir, "config.json", {})
    summary = _load(run_dir, "run_summary.json", {})
    metrics = _load(run_dir, "metrics.json", [])
    gate = _load(run_dir, "gate_result.json", None)

    totals = summary.get("totals", {})
    headline = summary.get("headline", {})
    cost = summary.get("cost", {})

    lines: list[str] = []
    lines.append(f"# 评测报告 — {summary.get('run_id', run_dir.name)}\n")

    # 隔离状态横幅
    if totals.get("contaminated"):
        lines.append("> 🔴 **CONTAMINATED** — 本次 run 改动了受保护文件，"
                     "结果不可信，门禁应硬失败。\n")
    else:
        lines.append("> 🟢 **隔离正常** — 主知识图谱与长期记忆未被改动。\n")

    # 元数据
    lines.append("## 运行元数据\n")
    lines.append("| 项 | 值 |")
    lines.append("|:---|:---|")
    lines.append(f"| run_id | {summary.get('run_id', '-')} |")
    lines.append(f"| 数据集版本 | {config.get('dataset_version', '-')} |")
    lines.append(f"| 代码版本 | {config.get('code_hash', '-')} |")
    lines.append(f"| 模型 | {config.get('model', '-')} |")
    lines.append(f"| 离线模式 | {config.get('offline', '-')} |")
    lines.append(f"| 时间 | {config.get('timestamp', '-')} |")
    lines.append("")

    # 总览
    lines.append("## 总览\n")
    lines.append("| 指标 | 值 |")
    lines.append("|:---|:---|")
    lines.append(f"| 任务总数 | {totals.get('total', 0)} |")
    lines.append(f"| 成功 / 失败 / 跳过 | {totals.get('ok', 0)} / "
                 f"{totals.get('failed', 0)} / {totals.get('skipped', 0)} |")
    lines.append(f"| 完成率 | {headline.get('completion_rate', 0)} |")
    lines.append(f"| 工具成功率 | {headline.get('tool_success_rate', 0)} |")
    lines.append(f"| p90 延迟 (ms) | {headline.get('p90_latency_ms', 0)} |")
    lines.append(f"| 总成本 (USD) | {headline.get('total_cost_usd', 0)} "
                 f"（估算方式: {cost.get('method', '-')}）|")
    if gate:
        lines.append(f"| 门禁结论 | **{gate.get('overall', '-')}** "
                     f"(pass {gate['summary']['pass']} / warn {gate['summary']['warn']} "
                     f"/ fail {gate['summary']['fail']}) |")
    lines.append("")

    # 各能力
    by_cap = summary.get("by_capability", {})
    if by_cap:
        lines.append("## 各能力完成情况\n")
        lines.append("| 能力 | 总数 | 成功 | 失败 | 跳过 | 完成率 |")
        lines.append("|:---|---:|---:|---:|---:|---:|")
        for cap, s in sorted(by_cap.items()):
            lines.append(f"| {cap} | {s['total']} | {s['ok']} | {s['failed']} | "
                         f"{s['skipped']} | {s['completion_rate']} |")
        lines.append("")

    # 各指标聚合
    by_metric = summary.get("by_metric", {})
    if by_metric:
        lines.append("## 指标聚合\n")
        lines.append("| 指标 | 均值 | n | min | max |")
        lines.append("|:---|---:|---:|---:|---:|")
        for name, s in sorted(by_metric.items()):
            lines.append(f"| {name} | {s.get('mean', 0)} | {s.get('n', 0)} | "
                         f"{s.get('min', 0)} | {s.get('max', 0)} |")
        lines.append("")

    # per-task 指标明细
    if metrics:
        lines.append("## per-task 指标明细\n")
        lines.append("| task_id | 指标 | 值 | 分子/分母 | notes |")
        lines.append("|:---|:---|---:|:---|:---|")
        for m in metrics:
            lines.append(
                f"| {m.get('task_id', '-')} | {m.get('metric', '-')} | "
                f"{m.get('value', 0)} | {m.get('numerator', 0)}/{m.get('denominator', 0)} "
                f"| {str(m.get('notes', ''))[:60]} |"
            )
        lines.append("")

    # 延迟
    latency = summary.get("latency", {})
    if latency:
        lines.append("## 工具延迟 (ms)\n")
        lines.append("| 工具 | mean | median | p90 | max | count |")
        lines.append("|:---|---:|---:|---:|---:|---:|")
        for tool, s in sorted(latency.items()):
            lines.append(f"| {tool} | {s.get('mean', 0)} | {s.get('median', 0)} | "
                         f"{s.get('p90', 0)} | {s.get('max', 0)} | {s.get('count', 0)} |")
        lines.append("")

    # 失败卡片引用
    failures_md = run_dir / "failures.md"
    if failures_md.exists():
        lines.append("## 失败卡片\n")
        lines.append(f"详见 [`failures.md`](failures.md)。\n")

    out = run_dir / "report.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
