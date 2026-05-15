from __future__ import annotations

"""
聚合层 —— per-task 指标计算 + run_summary.json 生成。

两步：
  1. compute_task_metrics: 对每个有 gold.metrics 的任务，按名字应用 METRIC_REGISTRY。
  2. aggregate_run: 把 per-task 指标按 (metric) 与 (capability) 分组聚合，
     连同 totals / latency / cost 产出 run_summary。
"""

import logging
import statistics
from typing import Any

from .cost import estimate_cost
from .dataset import Dataset
from .metrics import METRIC_REGISTRY, apply_metric, latency_stats
from .schema import MetricResult, RunConfig, TaskResult, TraceEvent

logger = logging.getLogger("AcademicAgent.Eval.Aggregate")


def compute_task_metrics(
    task_results: list[TaskResult],
    dataset: Dataset,
) -> list[MetricResult]:
    """对每个任务应用其 gold.metrics 里声明的指标。

    - status != "ok" 的任务不算指标（失败/跳过的任务交给 failure_cards 处理）。
    - 未知指标名记 warning 并跳过（dataset.validate() 本应已拦截）。
    """
    task_by_id = {t.task_id: t for t in dataset.tasks}
    out: list[MetricResult] = []
    for tr in task_results:
        if tr.status != "ok":
            continue
        spec = task_by_id.get(tr.task_id)
        if spec is None or not spec.gold.metrics:
            continue
        gold = dataset.gold_for(spec)
        for metric_name in spec.gold.metrics:
            if metric_name not in METRIC_REGISTRY:
                logger.warning("未知指标 %s（任务 %s），跳过", metric_name, tr.task_id)
                continue
            try:
                out.append(apply_metric(metric_name, tr, gold))
            except Exception as exc:  # noqa: BLE001
                logger.warning("指标 %s 计算失败（任务 %s）: %s",
                               metric_name, tr.task_id, exc)
    return out


def _agg(values: list[float]) -> dict:
    if not values:
        return {"mean": 0.0, "n": 0, "min": 0.0, "max": 0.0}
    return {
        "mean": round(statistics.mean(values), 4),
        "n": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def aggregate_run(
    config: RunConfig,
    task_results: list[TaskResult],
    task_metrics: list[MetricResult],
    traces: list[TraceEvent],
    contamination: dict | None = None,
) -> dict[str, Any]:
    """生成 run_summary.json 的内容。"""
    totals = {
        "total": len(task_results),
        "ok": sum(1 for r in task_results if r.status == "ok"),
        "failed": sum(1 for r in task_results if r.status == "failed"),
        "skipped": sum(1 for r in task_results if r.status == "skipped"),
        "contaminated": bool((contamination or {}).get("contaminated", False)),
        "changed_paths": (contamination or {}).get("changed_paths", []),
    }

    # 按指标名聚合
    by_metric: dict[str, dict] = {}
    metric_values: dict[str, list[float]] = {}
    for m in task_metrics:
        metric_values.setdefault(m.metric, []).append(m.value)
    for name, vals in metric_values.items():
        by_metric[name] = _agg(vals)

    # 按能力聚合（completion_rate 维度）
    by_capability: dict[str, dict] = {}
    cap_groups: dict[str, list[TaskResult]] = {}
    for r in task_results:
        cap_groups.setdefault(r.capability, []).append(r)
    for cap, group in cap_groups.items():
        non_skipped = [r for r in group if r.status != "skipped"]
        ok = sum(1 for r in non_skipped if r.status == "ok")
        by_capability[cap] = {
            "total": len(group),
            "ok": ok,
            "failed": sum(1 for r in non_skipped if r.status == "failed"),
            "skipped": sum(1 for r in group if r.status == "skipped"),
            "completion_rate": round(ok / len(non_skipped), 4) if non_skipped else 0.0,
        }

    # 全局工具成功率（从 trace）
    tool_events = [t for t in traces if t.event_type in ("tool_call", "workflow_step")]
    tool_ok = sum(1 for t in tool_events if t.ok)
    tool_success_rate = round(tool_ok / len(tool_events), 4) if tool_events else 0.0
    by_metric.setdefault("tool_success_rate", {
        "mean": tool_success_rate, "n": len(tool_events),
        "min": tool_success_rate, "max": tool_success_rate,
    })
    non_skipped_all = [r for r in task_results if r.status != "skipped"]
    completion = (
        round(sum(1 for r in non_skipped_all if r.status == "ok") / len(non_skipped_all), 4)
        if non_skipped_all else 0.0
    )
    by_metric.setdefault("completion_rate", {
        "mean": completion, "n": len(non_skipped_all),
        "min": completion, "max": completion,
    })

    # ---- 软指标: lesson_assisted_rate ---------------------------------------
    # 衡量"被 critic 救活"的任务占比。warn-only —— 不进硬门禁，仅作趋势观测：
    #   numerator   = 任务成功 且 (有 pre_hints 或 critic 触发了重试)
    #   denominator = 所有非 skipped 任务
    # 趋势上升 -> critic 在挽救更多任务（说明历史飞轮有效）
    # 趋势下降 -> 要么底层 bug 被根治（好事），要么 critic 失效（坏事）
    # 需结合 completion_rate / by_metric 一起读。
    assisted_ok = 0
    for r in task_results:
        critic = (r.raw or {}).get("_critic") or {}
        if (r.status == "ok"
                and (bool(critic.get("pre_hints"))
                     or int(critic.get("retries_used", 0)) > 0)):
            assisted_ok += 1
    assisted_rate = (
        round(assisted_ok / len(non_skipped_all), 4) if non_skipped_all else 0.0
    )
    by_metric.setdefault("lesson_assisted_rate", {
        "mean": assisted_rate, "n": len(non_skipped_all),
        "min": assisted_rate, "max": assisted_rate,
    })

    # 延迟
    latency = latency_stats(traces)

    # 成本
    total_tokens_in = sum(r.tokens_in for r in task_results)
    total_tokens_out = sum(r.tokens_out for r in task_results)
    cost_est = estimate_cost(
        total_tokens_in, total_tokens_out,
        model=config.model or "_default",
        method="char_heuristic",
    )
    cost_by_layer: dict[str, dict] = {}
    layer_groups: dict[str, list[TaskResult]] = {}
    for r in task_results:
        layer_groups.setdefault(r.layer, []).append(r)
    for layer, group in layer_groups.items():
        t_in = sum(r.tokens_in for r in group)
        t_out = sum(r.tokens_out for r in group)
        cost_by_layer[layer] = estimate_cost(
            t_in, t_out, model=config.model or "_default", method="char_heuristic"
        ).to_dict()

    p90_all = latency.get("__all__", {}).get("p90", 0.0)
    avg_cost_per_task = (
        round(cost_est.usd / totals["total"], 6) if totals["total"] else 0.0
    )

    return {
        "run_id": config.run_id,
        "dataset_version": config.dataset_version,
        "dataset_sha256": config.dataset_sha256,
        "code_hash": config.code_hash,
        "tiers": config.tiers,
        "layers": config.layers,
        "model": config.model,
        "offline": config.offline,
        "timestamp": config.timestamp,
        "totals": totals,
        "by_metric": by_metric,
        "by_capability": by_capability,
        "latency": latency,
        "cost": {
            "total_usd": round(cost_est.usd, 6),
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
            "method": cost_est.method,
            "avg_cost_usd_per_task": avg_cost_per_task,
            "by_layer": cost_by_layer,
        },
        "headline": {
            "completion_rate": completion,
            "tool_success_rate": tool_success_rate,
            "p90_latency_ms": p90_all,
            "total_cost_usd": round(cost_est.usd, 6),
        },
    }
