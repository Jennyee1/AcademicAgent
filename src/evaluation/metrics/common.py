from __future__ import annotations

"""
通用指标 —— 工具成功率、任务完成率、延迟统计。

所有函数都是纯函数：输入 trace / task_result，输出 MetricResult 或 dict。
"""

import statistics
from collections import defaultdict

from ..schema import MetricResult, TaskResult, TraceEvent


def tool_success_rate(
    traces: list[TraceEvent],
    tool_name: str | None = None,
) -> MetricResult:
    """ok=True 的 tool_call / workflow_step 事件占比。tool_name 给定时只统计该工具。"""
    relevant = [
        t for t in traces
        if t.event_type in ("tool_call", "workflow_step")
        and (tool_name is None or t.tool_name == tool_name)
    ]
    suffix = f"_{tool_name}" if tool_name else ""
    if not relevant:
        return MetricResult(
            metric=f"tool_success_rate{suffix}",
            value=0.0, numerator=0, denominator=0,
            notes="no tool_call events found",
        )
    ok_count = sum(1 for t in relevant if t.ok)
    return MetricResult(
        metric=f"tool_success_rate{suffix}",
        value=ok_count / len(relevant),
        numerator=float(ok_count),
        denominator=float(len(relevant)),
    )


def completion_rate(task_results: list[TaskResult]) -> MetricResult:
    """非 skipped 任务中 status == 'ok' 的占比。skipped 任务不计入分母。"""
    non_skipped = [r for r in task_results if r.status != "skipped"]
    if not non_skipped:
        return MetricResult(
            metric="completion_rate",
            value=0.0, numerator=0, denominator=0,
            notes="all tasks skipped",
        )
    completed = sum(1 for r in non_skipped if r.status == "ok")
    return MetricResult(
        metric="completion_rate",
        value=completed / len(non_skipped),
        numerator=float(completed),
        denominator=float(len(non_skipped)),
    )


def _percentile(sorted_vals: list[float], q: float) -> float:
    """sorted_vals 已排序，q 取 [0,1]。"""
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    idx = max(0, min(n - 1, int(q * n) - 1)) if q * n >= 1 else 0
    return sorted_vals[idx]


def latency_stats(traces: list[TraceEvent]) -> dict:
    """按 tool_name 统计 {mean, median, p50, p90, max, count}，含 __all__ 聚合。"""
    by_tool: dict[str, list[float]] = defaultdict(list)
    for t in traces:
        if t.event_type in ("tool_call", "workflow_step"):
            by_tool[t.tool_name].append(t.latency_ms)
            by_tool["__all__"].append(t.latency_ms)

    result: dict[str, dict] = {}
    for tool, vals in by_tool.items():
        sv = sorted(vals)
        result[tool] = {
            "mean": round(statistics.mean(sv), 2),
            "median": round(statistics.median(sv), 2),
            "p50": round(_percentile(sv, 0.5), 2),
            "p90": round(_percentile(sv, 0.9), 2),
            "max": round(max(sv), 2),
            "count": len(sv),
        }
    return result
