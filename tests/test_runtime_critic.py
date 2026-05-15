from __future__ import annotations

"""Phase: runtime self-correction —— critic 单元 + layer1 集成。

覆盖三种场景：
  A. 历史 rate_limit 卡片 -> pre-hint 注入 backoff_ms -> 首次调用即成功（预防）
  B. 无历史 + 运行时 rate_limit 失败 -> critic 决策重试 + backoff -> 第二次成功（自纠错）
  C. 历史命中 MiniMax 200-char schema bug 模式 -> critic 识别为不可修 -> 不重试（节省 token）
"""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.evaluation.adapters.base import (
    ADAPTER_REGISTRY,
    AdapterContext,
    ToolCallResult,
    register_adapter,
)
from src.evaluation.critic import (
    CriticDecision,
    decide_after_failure,
    derive_pre_hints,
)
from src.evaluation.failure_lookup import FailureLesson
from src.evaluation.layers.layer1_component import run_component_task
from src.evaluation.schema import (
    Capability,
    EvalLayer,
    GoldRef,
    TargetSpec,
    TaskSpec,
    Tier,
)
from src.evaluation.tracer import Tracer


# ---- critic 单元测试 ---------------------------------------------------------


def _lesson(category: str, severity: str = "P1", root_cause: str = "") -> FailureLesson:
    return FailureLesson(
        card_id="t#1", task_id="t", layer="layer1_component",
        capability="retrieval", tool="search_papers",
        category=category, severity=severity,
        root_cause_hypothesis=root_cause, fix_candidate="",
        tags=(),
    )


def test_pre_hints_empty_history_returns_empty():
    assert derive_pre_hints([], tool="search_papers") == {}


def test_pre_hints_rate_limit_history_injects_backoff():
    hints = derive_pre_hints([_lesson("rate_limit")], tool="search_papers")
    assert hints.get("backoff_ms") == 2000


def test_pre_hints_llm_api_error_history_injects_retry_delay():
    hints = derive_pre_hints(
        [_lesson("llm_api_error", root_cause="transient blip")],
        tool="extract_from_text",
    )
    assert hints.get("retry_delay_ms") == 1000


def test_critic_retries_on_rate_limit():
    d = decide_after_failure(
        error_category="rate_limit", lessons=[], retries_used=0,
    )
    assert d.should_retry is True
    assert d.hints.get("backoff_ms")


def test_critic_retries_transient_llm_error():
    d = decide_after_failure(
        error_category="llm_api_error", lessons=[], retries_used=0,
    )
    assert d.should_retry is True
    assert d.hints.get("retry_delay_ms")


def test_critic_does_not_retry_known_minimax_bug():
    # 根因里同时提到 "description" 和 "200" => 识别为已知不可修
    lesson = _lesson(
        "llm_api_error", "P0",
        root_cause="MiniMax 对 description 字段长度上限是 200 字符，schema 超限导致 400",
    )
    d = decide_after_failure(
        error_category="llm_api_error", lessons=[lesson], retries_used=0,
    )
    assert d.should_retry is False
    assert "known unfixable" in d.reason.lower()


def test_critic_no_retry_when_budget_exhausted():
    d = decide_after_failure(
        error_category="rate_limit", lessons=[], retries_used=1, max_retries=1,
    )
    assert d.should_retry is False
    assert "budget" in d.reason.lower()


def test_critic_no_retry_on_empty_extraction():
    d = decide_after_failure(
        error_category="empty_extraction", lessons=[], retries_used=0,
    )
    assert d.should_retry is False


# ---- layer1 集成测试 ---------------------------------------------------------


@dataclass
class _DummyDataset:
    path: Path

    def gold_for(self, task):  # noqa: ARG002 — 占位实现
        return None


def _plant_card(failure_cards_dir: Path, card: dict) -> None:
    failure_cards_dir.mkdir(parents=True, exist_ok=True)
    with open(failure_cards_dir / "prior.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(card) + "\n")


def _setup_run_dirs(tmp_path: Path) -> tuple[Path, Path]:
    """返回 (run_dir, failure_cards_dir)；二者位置遵循生产布局。"""
    eval_root = tmp_path / "data" / "evaluation"
    run_dir = eval_root / "runs" / "test_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    failure_cards_dir = eval_root / "failure_cards"
    return run_dir, failure_cards_dir


def _make_task(tool: str) -> TaskSpec:
    return TaskSpec(
        task_id="critic_smoke",
        layer=EvalLayer.COMPONENT,
        capability=Capability.RETRIEVAL,
        tier=Tier.SMOKE,
        target=TargetSpec(tool=tool, args={}),
        gold=GoldRef(),
        timeout_s=10,
    )


@pytest.fixture
def registered_adapters():
    """在测试中注册 fake adapter 并在结束时清理，避免污染全局 ADAPTER_REGISTRY。"""
    registered: list[str] = []

    def _register(name, fn):
        register_adapter(name)(fn)
        registered.append(name)

    yield _register

    for name in registered:
        ADAPTER_REGISTRY.pop(name, None)


@pytest.mark.asyncio
async def test_pre_hint_prevents_first_call_failure(tmp_path: Path, registered_adapters):
    """场景 A：历史 rate_limit -> pre-hint -> 首次调用就拿到 backoff_ms，成功。"""
    run_dir, fc_dir = _setup_run_dirs(tmp_path)
    _plant_card(fc_dir, {
        "card_id": "prior#1", "task_id": "old_task",
        "layer": "layer1_component", "capability": "retrieval",
        "category": "rate_limit", "severity": "P1",
        "repro_command": "... __flaky_rl__ ...",
        "trace_excerpt": "", "root_cause_hypothesis": "S2 429 在过去 run 里出现过",
        "fix_candidate": "", "regression_test_suggestion": "",
        "detail": "", "tags": ["rate_limit", "__flaky_rl__"],
    })

    calls: dict = {"n": 0, "hints_seen": []}

    async def flaky(args, ctx: AdapterContext):
        calls["n"] += 1
        calls["hints_seen"].append(dict(ctx.hints))
        # 有 backoff_ms 即成功，否则 rate_limit
        if ctx.hints.get("backoff_ms"):
            return ToolCallResult(ok=True, tool="__flaky_rl__", raw={"ok": True})
        return ToolCallResult.failure("__flaky_rl__", "S2 429", "rate_limit")

    registered_adapters("__flaky_rl__", flaky)

    task = _make_task("__flaky_rl__")
    tracer = Tracer(run_id="test_run", traces_path=run_dir / "traces.jsonl")
    result = await run_component_task(task, _DummyDataset(tmp_path), run_dir, tracer)

    assert result.status == "ok"
    assert calls["n"] == 1, "pre-hint 应让首次调用就成功，不需重试"
    assert calls["hints_seen"][0].get("backoff_ms") == 2000
    critic = result.raw.get("_critic", {})
    assert critic.get("retries_used") == 0
    assert critic.get("pre_hints", {}).get("backoff_ms") == 2000
    assert critic.get("lesson_assisted_ok") is True


@pytest.mark.asyncio
async def test_critic_retries_after_runtime_failure(tmp_path: Path, registered_adapters):
    """场景 B：无历史 -> 首次失败 rate_limit -> critic 重试 + backoff -> 第二次成功。"""
    run_dir, _fc_dir = _setup_run_dirs(tmp_path)
    # 故意不写任何历史卡片

    calls: dict = {"n": 0, "hints_seen": []}

    async def flaky(args, ctx: AdapterContext):
        calls["n"] += 1
        calls["hints_seen"].append(dict(ctx.hints))
        if ctx.hints.get("backoff_ms"):
            return ToolCallResult(ok=True, tool="__flaky_rl2__", raw={"ok": True})
        return ToolCallResult.failure("__flaky_rl2__", "S2 429", "rate_limit")

    registered_adapters("__flaky_rl2__", flaky)

    task = _make_task("__flaky_rl2__")
    tracer = Tracer(run_id="test_run", traces_path=run_dir / "traces.jsonl")
    result = await run_component_task(task, _DummyDataset(tmp_path), run_dir, tracer)

    assert result.status == "ok"
    assert calls["n"] == 2, "首次应失败，critic 触发一次重试，共 2 次调用"
    # 首次调用无 hints；第二次应带有 critic 注入的 backoff_ms
    assert not calls["hints_seen"][0].get("backoff_ms")
    assert calls["hints_seen"][1].get("backoff_ms")
    critic = result.raw.get("_critic", {})
    assert critic.get("retries_used") == 1
    assert critic.get("lesson_assisted_ok") is True


@pytest.mark.asyncio
async def test_critic_aborts_known_unfixable_pattern(tmp_path: Path, registered_adapters):
    """场景 C：历史命中 MiniMax 200-char schema bug -> critic 不重试，节省 token。"""
    run_dir, fc_dir = _setup_run_dirs(tmp_path)
    _plant_card(fc_dir, {
        "card_id": "prior#kg", "task_id": "old_kg_task",
        "layer": "layer1_component", "capability": "retrieval",
        "category": "llm_api_error", "severity": "P0",
        "repro_command": "... __flaky_kg__ ...",
        "trace_excerpt": "",
        "root_cause_hypothesis":
            "MiniMax 对 json_schema 的 property description 有长度上限（max 200 字符），"
            "ExtractionOutput 的 schema 描述超限导致 400。",
        "fix_candidate": "", "regression_test_suggestion": "",
        "detail": "", "tags": ["__flaky_kg__"],
    })

    calls: dict = {"n": 0}

    async def flaky_kg(args, ctx: AdapterContext):
        calls["n"] += 1
        return ToolCallResult.failure(
            "__flaky_kg__", "MiniMax 400 description too long", "llm_api_error",
        )

    registered_adapters("__flaky_kg__", flaky_kg)

    task = _make_task("__flaky_kg__")
    tracer = Tracer(run_id="test_run", traces_path=run_dir / "traces.jsonl")
    result = await run_component_task(task, _DummyDataset(tmp_path), run_dir, tracer)

    assert result.status == "failed"
    assert result.error_category == "llm_api_error"
    # 关键断言：critic 识别已知不可修模式后不应触发重试 -> 仅 1 次调用
    assert calls["n"] == 1
    critic = result.raw.get("_critic", {})
    assert critic.get("retries_used") == 0
    decisions = critic.get("decisions", [])
    assert any("unfixable" in r.lower() for r in decisions)
