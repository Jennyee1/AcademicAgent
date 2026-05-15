from __future__ import annotations

"""评测指标纯函数单测。"""

from src.evaluation.metrics import (
    METRIC_REGISTRY,
    code_success_rate,
    completion_rate,
    extraction_nonempty_rate,
    figure_type_accuracy,
    gap_type_match,
    kg_edge_f1,
    kg_node_f1,
    latency_stats,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    schema_validity_rate,
    stdout_assertion_pass,
    tool_sequence_match,
    tool_success_rate,
)
from src.evaluation.schema import TaskResult, TraceEvent


def _trace(tool="t", ok=True, latency=10.0, etype="tool_call"):
    return TraceEvent(run_id="r", task_id="x", ts="ts", event_type=etype,
                      tool_name=tool, ok=ok, latency_ms=latency)


# ------------------- common -------------------

def test_tool_success_rate():
    traces = [_trace(ok=True), _trace(ok=True), _trace(ok=False)]
    m = tool_success_rate(traces)
    assert m.value == 2 / 3 and m.numerator == 2 and m.denominator == 3


def test_tool_success_rate_empty():
    assert tool_success_rate([]).value == 0.0


def test_completion_rate_excludes_skipped():
    results = [
        TaskResult(task_id="a", layer="l", capability="c", status="ok"),
        TaskResult(task_id="b", layer="l", capability="c", status="failed"),
        TaskResult(task_id="c", layer="l", capability="c", status="skipped"),
    ]
    m = completion_rate(results)
    assert m.value == 0.5 and m.denominator == 2  # skipped 不计入分母


def test_latency_stats():
    traces = [_trace(latency=10.0), _trace(latency=20.0), _trace(latency=30.0)]
    stats = latency_stats(traces)
    assert stats["__all__"]["count"] == 3
    assert stats["__all__"]["max"] == 30.0


# ------------------- retrieval -------------------

def test_recall_at_k():
    m = recall_at_k(["A", "B", "C"], ["b", "x"], k=3)
    assert m.value == 0.5  # 命中 b，gold 有 2 个


def test_precision_at_k():
    m = precision_at_k(["A", "B", "C"], ["a", "b"], k=3)
    assert abs(m.value - 2 / 3) < 1e-9


def test_mrr_first_and_none():
    assert mrr(["x", "gold"], ["gold"]).value == 0.5
    assert mrr(["x", "y"], ["gold"]).value == 0.0


def test_ndcg_perfect():
    m = ndcg_at_k(["a", "b"], ["a", "b"], k=2)
    assert abs(m.value - 1.0) < 1e-9


# ------------------- kg -------------------

def test_kg_node_f1_partial():
    extracted = [{"label": "ReAct", "node_type": "method"},
                 {"label": "Wrong", "node_type": "concept"}]
    gold = [{"label": "ReAct", "node_type": "method"},
            {"label": "Tool", "node_type": "concept"}]
    m = kg_node_f1(extracted, gold)
    assert m.value == 0.5  # P=0.5, R=0.5 -> F1=0.5


def test_kg_node_f1_both_empty():
    assert kg_node_f1([], []).value == 1.0


def test_kg_edge_f1_from_node_ids():
    extracted = [{"source_id": "method_react", "target_id": "concept_tool_use",
                  "relation_type": "uses"}]
    gold = [{"source_label": "ReAct", "relation_type": "uses", "target_label": "tool use"}]
    m = kg_edge_f1(extracted, gold)
    assert m.value == 1.0


def test_schema_validity_rate():
    nodes = [{"node_type": "method"}, {"node_type": "bogus"}]
    m = schema_validity_rate(nodes, [])
    assert m.value == 0.5


def test_extraction_nonempty_rate():
    assert extraction_nonempty_rate([{"label": "x", "node_type": "method"}], []).value == 1.0
    assert extraction_nonempty_rate([], []).value == 0.0


# ------------------- capability -------------------

def test_code_success_rate():
    assert code_success_rate(True, expect_success=True).value == 1.0
    assert code_success_rate(False, expect_success=True).value == 0.0


def test_stdout_assertion_pass():
    m = stdout_assertion_pass("sum= 45\nagent eval ok", ["sum= 45", "agent eval ok"])
    assert m.value == 1.0


def test_gap_type_match():
    m = gap_type_match(["isolated_concept", "foundation_gap"], ["isolated_concept"])
    assert m.value == 1.0


def test_figure_type_accuracy():
    assert figure_type_accuracy("performance_curve", "performance_curve").value == 1.0
    assert figure_type_accuracy("table", "performance_curve").value == 0.0


# ------------------- workflow -------------------

def test_tool_sequence_match():
    m = tool_sequence_match(["a", "b", "x"], ["a", "b", "c"])
    assert abs(m.value - 2 / 3) < 1e-9


# ------------------- registry -------------------

def test_registry_apply():
    from src.evaluation.metrics import apply_metric
    tr = TaskResult(task_id="t1", layer="layer1_component", capability="kg_extraction",
                    status="ok", raw={"nodes": [{"label": "ReAct", "node_type": "method"}],
                                       "edges": []})
    gold = {"expected_nodes": [{"label": "ReAct", "node_type": "method"}], "expected_edges": []}
    m = apply_metric("kg_node_f1", tr, gold)
    assert m.value == 1.0 and m.task_id == "t1" and m.capability == "kg_extraction"


def test_registry_has_expected_metrics():
    for name in ("recall_at_5", "kg_node_f1", "code_success_rate",
                 "gap_type_match", "tool_sequence_match", "mrr"):
        assert name in METRIC_REGISTRY
