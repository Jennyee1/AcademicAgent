from __future__ import annotations

"""
评测指标包 —— 纯函数 + 统一注册表。

两层结构：
  1. 子模块（common / retrieval / kg / capability / workflow）：纯计算函数。
  2. METRIC_REGISTRY：name -> wrapper(task_result, gold) -> MetricResult。
     wrapper 负责从 task_result.raw + gold 里取出该指标需要的字段，
     再调用纯函数。layer runner 按 GoldRef.metrics 里的名字查表应用。

新增指标 = 写一个纯函数 + 注册一个 wrapper。
"""

from typing import Callable

from ..schema import MetricResult, TaskResult
from . import capability, common, kg, retrieval, workflow

# 重导出纯函数，方便聚合层与单测直接使用
from .common import completion_rate, latency_stats, tool_success_rate  # noqa: F401
from .retrieval import mrr, ndcg_at_k, precision_at_k, recall_at_k  # noqa: F401
from .kg import (  # noqa: F401
    extraction_nonempty_rate,
    kg_edge_f1,
    kg_node_f1,
    schema_validity_rate,
)
from .capability import (  # noqa: F401
    artifact_produced_rate,
    code_success_rate,
    figure_entity_recall,
    figure_type_accuracy,
    gap_label_recall,
    gap_type_match,
    neighbor_recall,
    query_hit_rate,
    stdout_assertion_pass,
    top_concept_overlap,
)
from .workflow import (  # noqa: F401
    final_assertion_pass,
    step_success_rate,
    tool_sequence_match,
    workflow_completion_rate,
)

# wrapper 签名：(task_result, gold) -> MetricResult
MetricWrapper = Callable[[TaskResult, "dict | None"], MetricResult]


def _g(gold: dict | None, key: str, default=None):
    return (gold or {}).get(key, default)


# ------------------------------------------------------------------ #
# Retrieval wrappers
# ------------------------------------------------------------------ #

def _retrieved(tr: TaskResult) -> list[str]:
    raw = tr.raw or {}
    # 优先用 paper_ids（外部 ID 更可靠），否则用 titles
    ids = raw.get("retrieved_ids") or []
    titles = raw.get("retrieved") or raw.get("retrieved_titles") or []
    return [str(x) for x in (ids if ids else titles)]


def _gold_items(gold: dict | None) -> list[str]:
    g = gold or {}
    ids = g.get("gold_paper_ids") or []
    titles = g.get("gold_titles") or []
    return [str(x) for x in (ids if ids else titles)]


def _make_recall(k: int) -> MetricWrapper:
    def w(tr: TaskResult, gold: dict | None) -> MetricResult:
        return recall_at_k(_retrieved(tr), _gold_items(gold), k=k, task_id=tr.task_id)
    return w


def _make_precision(k: int) -> MetricWrapper:
    def w(tr: TaskResult, gold: dict | None) -> MetricResult:
        return precision_at_k(_retrieved(tr), _gold_items(gold), k=k, task_id=tr.task_id)
    return w


def _make_ndcg(k: int) -> MetricWrapper:
    def w(tr: TaskResult, gold: dict | None) -> MetricResult:
        return ndcg_at_k(_retrieved(tr), _gold_items(gold), k=k, task_id=tr.task_id)
    return w


def _mrr(tr: TaskResult, gold: dict | None) -> MetricResult:
    return mrr(_retrieved(tr), _gold_items(gold), task_id=tr.task_id)


# ------------------------------------------------------------------ #
# KG wrappers
# ------------------------------------------------------------------ #

def _kg_node_f1(tr: TaskResult, gold: dict | None) -> MetricResult:
    return kg_node_f1(
        tr.raw.get("nodes", []), _g(gold, "expected_nodes", []), task_id=tr.task_id
    )


def _kg_edge_f1(tr: TaskResult, gold: dict | None) -> MetricResult:
    return kg_edge_f1(
        tr.raw.get("edges", []), _g(gold, "expected_edges", []), task_id=tr.task_id
    )


def _schema_validity(tr: TaskResult, gold: dict | None) -> MetricResult:
    return schema_validity_rate(
        tr.raw.get("nodes", []), tr.raw.get("edges", []), task_id=tr.task_id
    )


def _extraction_nonempty(tr: TaskResult, gold: dict | None) -> MetricResult:
    return extraction_nonempty_rate(
        tr.raw.get("nodes", []), tr.raw.get("edges", []), task_id=tr.task_id
    )


# ------------------------------------------------------------------ #
# Capability wrappers
# ------------------------------------------------------------------ #

def _query_hit_rate(tr: TaskResult, gold: dict | None) -> MetricResult:
    return query_hit_rate(
        tr.raw.get("matched_labels", []), _g(gold, "expected_labels", []), task_id=tr.task_id
    )


def _neighbor_recall(tr: TaskResult, gold: dict | None) -> MetricResult:
    return neighbor_recall(
        tr.raw.get("neighbors", []), _g(gold, "expected_neighbors", []), task_id=tr.task_id
    )


def _gap_type_match(tr: TaskResult, gold: dict | None) -> MetricResult:
    return gap_type_match(
        tr.raw.get("detected_gap_types", []), _g(gold, "expected_gap_types", []), task_id=tr.task_id
    )


def _gap_label_recall(tr: TaskResult, gold: dict | None) -> MetricResult:
    return gap_label_recall(
        tr.raw.get("detected_gap_labels", []), _g(gold, "expected_gap_labels", []), task_id=tr.task_id
    )


def _top_concept_overlap(tr: TaskResult, gold: dict | None) -> MetricResult:
    return top_concept_overlap(
        tr.raw.get("top_concepts", []), _g(gold, "expected_top_concepts", []), task_id=tr.task_id
    )


def _code_success_rate(tr: TaskResult, gold: dict | None) -> MetricResult:
    return code_success_rate(
        tr.raw.get("success", False), _g(gold, "expect_success", True), task_id=tr.task_id
    )


def _stdout_assertion_pass(tr: TaskResult, gold: dict | None) -> MetricResult:
    return stdout_assertion_pass(
        tr.raw.get("stdout", ""), _g(gold, "expect_stdout_contains", []), task_id=tr.task_id
    )


def _artifact_produced_rate(tr: TaskResult, gold: dict | None) -> MetricResult:
    return artifact_produced_rate(
        tr.raw.get("output_files", []), _g(gold, "expect_artifact", False), task_id=tr.task_id
    )


def _figure_type_accuracy(tr: TaskResult, gold: dict | None) -> MetricResult:
    return figure_type_accuracy(
        tr.raw.get("figure_type", ""), _g(gold, "expect_figure_type", ""), task_id=tr.task_id
    )


def _figure_entity_recall(tr: TaskResult, gold: dict | None) -> MetricResult:
    return figure_entity_recall(
        tr.raw.get("entities", []), _g(gold, "expect_entities_contains", []), task_id=tr.task_id
    )


# ------------------------------------------------------------------ #
# Workflow wrappers
# ------------------------------------------------------------------ #

def _workflow_completion_rate(tr: TaskResult, gold: dict | None) -> MetricResult:
    return workflow_completion_rate(tr.raw.get("all_steps_ok", False), task_id=tr.task_id)


def _tool_sequence_match(tr: TaskResult, gold: dict | None) -> MetricResult:
    return tool_sequence_match(
        tr.raw.get("actual_tool_sequence", []),
        _g(gold, "expected_tool_sequence", []),
        task_id=tr.task_id,
    )


def _step_success_rate(tr: TaskResult, gold: dict | None) -> MetricResult:
    return step_success_rate(tr.raw.get("step_ok", []), task_id=tr.task_id)


def _final_assertion_pass(tr: TaskResult, gold: dict | None) -> MetricResult:
    return final_assertion_pass(tr.raw.get("final_assertion_results", []), task_id=tr.task_id)


# ------------------------------------------------------------------ #
# 注册表
# ------------------------------------------------------------------ #

METRIC_REGISTRY: dict[str, MetricWrapper] = {
    # retrieval
    "recall_at_5": _make_recall(5),
    "recall_at_10": _make_recall(10),
    "precision_at_5": _make_precision(5),
    "precision_at_10": _make_precision(10),
    "ndcg_at_5": _make_ndcg(5),
    "ndcg_at_10": _make_ndcg(10),
    "mrr": _mrr,
    # kg extraction
    "kg_node_f1": _kg_node_f1,
    "kg_edge_f1": _kg_edge_f1,
    "schema_validity_rate": _schema_validity,
    "extraction_nonempty_rate": _extraction_nonempty,
    # kg query
    "query_hit_rate": _query_hit_rate,
    "neighbor_recall": _neighbor_recall,
    # gap detection
    "gap_type_match": _gap_type_match,
    "gap_label_recall": _gap_label_recall,
    "top_concept_overlap": _top_concept_overlap,
    # code exec
    "code_success_rate": _code_success_rate,
    "stdout_assertion_pass": _stdout_assertion_pass,
    "artifact_produced_rate": _artifact_produced_rate,
    # figure analysis
    "figure_type_accuracy": _figure_type_accuracy,
    "figure_entity_recall": _figure_entity_recall,
    # workflow
    "workflow_completion_rate": _workflow_completion_rate,
    "tool_sequence_match": _tool_sequence_match,
    "step_success_rate": _step_success_rate,
    "final_assertion_pass": _final_assertion_pass,
}


def apply_metric(name: str, task_result: TaskResult, gold: dict | None) -> MetricResult:
    """按名字应用一个指标。未知指标名抛 KeyError。"""
    wrapper = METRIC_REGISTRY[name]
    result = wrapper(task_result, gold)
    result.task_id = task_result.task_id
    result.layer = task_result.layer
    result.capability = task_result.capability
    return result
