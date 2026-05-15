from __future__ import annotations

"""Phase 3 验证：L2 工作流注册表 + layer2 runner（用离线 learn_flow）。"""

import asyncio
from pathlib import Path

from src.evaluation.dataset import load_dataset
from src.evaluation.layers.layer2_workflow import run_workflow_task
from src.evaluation.schema import EvalLayer, Tier
from src.evaluation.tracer import Tracer
from src.evaluation.workflows.registry import all_workflows, get_workflow


def test_workflow_registry_populated():
    wfs = all_workflows()
    assert "learn_flow" in wfs
    assert "survey_flow" in wfs
    learn = get_workflow("learn_flow")
    assert [s.tool for s in learn.steps] == [
        "detect_gaps", "get_concept_importance", "analyze_knowledge",
    ]


def test_workflow_step_args_threading():
    survey = get_workflow("survey_flow")
    # step1 args_fn 读取初始 prev（task.target.args）
    args1 = survey.steps[0].args_fn({"query": "X", "limit": 2})
    assert args1 == {"query": "X", "limit": 2}
    # step2 args_fn 读取 step1 capture 的 first_paper_id
    args2 = survey.steps[1].args_fn({"first_paper_id": "abc123"})
    assert args2 == {"paper_id": "abc123"}


def test_learn_flow_runs_offline_in_shared_sandbox(tmp_path: Path):
    """learn_flow 在 seed 图谱上离线跑通，序列匹配、终态断言通过。"""
    dataset = load_dataset("data/evaluation/datasets/smoke")
    learn_task = next(
        t for t in dataset.tasks
        if t.task_id == "smoke_wf_learn" and t.layer == EvalLayer.WORKFLOW
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    tracer = Tracer("test", run_dir / "traces.jsonl")

    result = asyncio.get_event_loop().run_until_complete(
        run_workflow_task(learn_task, dataset, run_dir, tracer, offline=True)
    )
    assert result.status == "ok"
    assert result.raw["actual_tool_sequence"] == [
        "detect_gaps", "get_concept_importance", "analyze_knowledge",
    ]
    assert result.raw["all_steps_ok"] is True
    assert all(result.raw["final_assertion_results"])
    # sidecar 图谱被 seed 了，trace 里应有 3 个 workflow_step 事件
    events = tracer.load_events()
    assert sum(1 for e in events if e.event_type == "workflow_step") == 3


def test_smoke_dataset_still_validates():
    dataset = load_dataset("data/evaluation/datasets/smoke")
    assert dataset.validate() == []
    assert len(dataset.filter(tier=Tier.SMOKE, layer=EvalLayer.WORKFLOW)) == 2
