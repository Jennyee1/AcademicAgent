from __future__ import annotations

"""评测数据模型的序列化往返测试。"""

from src.evaluation.schema import (
    Capability,
    EvalLayer,
    GoldRef,
    MetricResult,
    RunConfig,
    TargetSpec,
    TaskResult,
    TaskSpec,
    Tier,
    TraceEvent,
)


def test_taskspec_roundtrip():
    d = {
        "task_id": "t1",
        "layer": "layer1_component",
        "capability": "kg_extraction",
        "tier": "smoke",
        "target": {"tool": "add_paper_to_graph", "args": {"text": "x"}},
        "gold": {"gold_file": "kg_gold.jsonl", "gold_key": "t1", "metrics": ["kg_node_f1"]},
        "timeout_s": 90,
        "requires_llm": True,
        "tags": ["kg"],
        "notes": "n",
    }
    t = TaskSpec.from_dict(d)
    assert t.layer == EvalLayer.COMPONENT
    assert t.capability == Capability.KG_EXTRACTION
    assert t.tier == Tier.SMOKE
    assert t.target.tool == "add_paper_to_graph"
    assert t.gold.metrics == ["kg_node_f1"]
    assert t.requires_llm is True
    again = TaskSpec.from_dict(t.to_dict())
    assert again.to_dict() == t.to_dict()


def test_targetspec_variants():
    wf = TargetSpec.from_dict({"workflow": "survey_flow"})
    assert wf.workflow == "survey_flow" and wf.tool is None
    e2e = TargetSpec.from_dict({"e2e_prompt": "do research"})
    assert e2e.e2e_prompt == "do research"
    assert TargetSpec.from_dict(None).to_dict() == {}


def test_goldref_defaults():
    g = GoldRef.from_dict(None)
    assert g.gold_file == "" and g.metrics == []


def test_traceevent_roundtrip_with_tokens():
    ev = TraceEvent(
        run_id="r", task_id="t", ts="2026-05-14T00:00:00.000+00:00",
        event_type="tool_call", tool_name="search_papers", ok=False,
        latency_ms=12.5, tokens_in=100, tokens_out=20,
        error="boom", error_category="timeout",
    )
    again = TraceEvent.from_dict(ev.to_dict())
    assert again.tokens_in == 100
    assert again.error_category == "timeout"
    assert again.ok is False


def test_metricresult_roundtrip():
    m = MetricResult(metric="kg_node_f1", value=0.5, task_id="t1",
                     layer="layer1_component", capability="kg_extraction",
                     numerator=1, denominator=2, notes="x")
    again = MetricResult.from_dict(m.to_dict())
    assert again.value == 0.5 and again.capability == "kg_extraction"


def test_taskresult_roundtrip():
    tr = TaskResult(
        task_id="t1", layer="layer1_component", capability="code_exec",
        status="ok", raw={"success": True}, latency_ms=33.0,
    )
    again = TaskResult.from_dict(tr.to_dict())
    assert again.status == "ok" and again.raw == {"success": True}


def test_runconfig_roundtrip():
    c = RunConfig(run_id="r1", dataset_path="d", tiers=["smoke"], offline=True)
    assert c.timestamp  # auto-filled
    again = RunConfig.from_dict(c.to_dict())
    assert again.run_id == "r1" and again.offline is True
