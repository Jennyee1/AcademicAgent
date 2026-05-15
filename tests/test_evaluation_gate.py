from __future__ import annotations

"""Phase 2 验证：回归门禁 + 失败卡片。"""

from src.evaluation.failure_cards import generate_failure_cards, render_failures_md
from src.evaluation.gate import run_gate
from src.evaluation.schema import MetricResult, TaskResult, TraceEvent


# ------------------- gate -------------------

def _summary(by_metric, contaminated=False, p90_ms=1000.0, avg_cost=0.0):
    return {
        "run_id": "r1",
        "by_metric": by_metric,
        "totals": {"contaminated": contaminated},
        "latency": {"__all__": {"p90": p90_ms}},
        "cost": {"avg_cost_usd_per_task": avg_cost},
    }


def test_gate_pass():
    thresholds = {"metrics": {"kg_node_f1": {"min": 0.4}}, "budget": {}}
    summary = _summary({"kg_node_f1": {"mean": 0.6, "n": 3}})
    res = run_gate(summary, thresholds)
    assert res["overall"] == "PASS" and res["exit_code"] == 0


def test_gate_fail_below_min():
    thresholds = {"metrics": {"kg_node_f1": {"min": 0.5}}, "budget": {}}
    summary = _summary({"kg_node_f1": {"mean": 0.2, "n": 3}})
    res = run_gate(summary, thresholds)
    assert res["overall"] == "FAIL" and res["exit_code"] == 1


def test_gate_warn_only_does_not_fail():
    thresholds = {"metrics": {"kg_node_f1": {"min": 0.5, "warn_only": True}}, "budget": {}}
    summary = _summary({"kg_node_f1": {"mean": 0.2, "n": 3}})
    res = run_gate(summary, thresholds)
    assert res["overall"] == "WARN" and res["exit_code"] == 0


def test_gate_contamination_hard_fails():
    thresholds = {"metrics": {}, "budget": {}}
    summary = _summary({}, contaminated=True)
    res = run_gate(summary, thresholds)
    assert res["overall"] == "FAIL" and res["exit_code"] == 1
    assert res["contaminated"] is True


def test_gate_budget_latency_fail():
    thresholds = {"metrics": {}, "budget": {"p90_latency_s": 1.0}}
    summary = _summary({}, p90_ms=5000.0)  # 5s > 1s
    res = run_gate(summary, thresholds)
    assert res["overall"] == "FAIL"


def test_gate_regression_vs_baseline():
    thresholds = {"metrics": {"mrr": {"min": 0.1, "regression_tolerance": 0.05}},
                  "budget": {}}
    summary = _summary({"mrr": {"mean": 0.5, "n": 3}})
    baseline = _summary({"mrr": {"mean": 0.8, "n": 3}})
    res = run_gate(summary, thresholds, baseline)
    # 0.5 < 0.8 - 0.05 -> regression FAIL
    assert res["overall"] == "FAIL"


# ------------------- failure cards -------------------

class _FakeDataset:
    def __init__(self, tmp_path):
        self.path = tmp_path


def test_failure_card_for_llm_api_error(tmp_path):
    ds = _FakeDataset(tmp_path)
    results = [TaskResult(
        task_id="smoke_kg_001", layer="layer1_component", capability="kg_extraction",
        status="failed", error="Error code: 400 description too long",
        error_category="llm_api_error",
    )]
    traces = [TraceEvent(run_id="r", task_id="smoke_kg_001", ts="ts",
                         event_type="tool_call", tool_name="add_paper_to_graph",
                         ok=False, error_category="llm_api_error")]
    cards = generate_failure_cards(ds, results, [], traces, run_id="r1",
                                   run_dir=tmp_path / "runs" / "r1")
    assert len(cards) == 1
    c = cards[0]
    assert c.category == "llm_api_error" and c.severity == "P0"
    assert "MiniMax" in c.root_cause_hypothesis
    assert "src.evaluation.cli run" in c.repro_command
    assert "extractor.py" in c.fix_candidate


def test_failure_card_for_metric_below_threshold(tmp_path):
    ds = _FakeDataset(tmp_path)
    results = [TaskResult(task_id="t", layer="l", capability="retrieval", status="ok")]
    metrics = [MetricResult(metric="recall_at_5", value=0.1, task_id="t")]
    thresholds = {"metrics": {"recall_at_5": {"min": 0.6}}}
    cards = generate_failure_cards(ds, results, metrics, [], run_id="r1",
                                   run_dir=tmp_path / "runs" / "r1",
                                   thresholds=thresholds)
    assert len(cards) == 1
    assert cards[0].category == "metric_below_threshold"


def test_failure_card_for_contamination(tmp_path):
    ds = _FakeDataset(tmp_path)
    cards = generate_failure_cards(
        ds, [], [], [], run_id="r1", run_dir=tmp_path / "runs" / "r1",
        contamination={"contaminated": True, "changed_paths": ["/x/knowledge_graph.json"]},
    )
    assert len(cards) == 1
    assert cards[0].category == "isolation_contamination"
    assert cards[0].severity == "P0"


def test_render_failures_md_empty():
    md = render_failures_md([], "r1")
    assert "没有失败" in md


def test_render_failures_md_with_cards(tmp_path):
    ds = _FakeDataset(tmp_path)
    results = [TaskResult(task_id="t", layer="l", capability="c", status="failed",
                          error="boom", error_category="timeout")]
    cards = generate_failure_cards(ds, results, [], [], run_id="r1",
                                   run_dir=tmp_path / "runs" / "r1")
    md = render_failures_md(cards, "r1")
    assert "timeout" in md and "复现" in md
