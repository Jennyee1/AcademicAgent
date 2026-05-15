from __future__ import annotations

"""
Runtime critic —— 把历史失败 lessons 转化为可执行的 hints + 重试决策。

这是一个 **确定性 (no-LLM) 控制器**:
  - derive_pre_hints   : 首次调用前生效, 用历史模式做"预防性"动作
  - decide_after_failure : 失败后审视错误类别 + 历史, 决定是否进行一次受限重试

重试预算由 runner 强制 (默认每任务 max_retries=1)。本模块只输出建议。
对应的 adapter 端约定 (key -> 含义):
  - backoff_ms      : adapter 在发出请求前 sleep N ms (用于 rate_limit)
  - retry_delay_ms  : 同上, 用于 transient llm_api_error / network blip
"""

from dataclasses import dataclass, field
from typing import Any

from .failure_lookup import FailureLesson

_MAX_BACKOFF_MS = 8000
_MAX_RETRY_DELAY_MS = 5000


@dataclass
class CriticDecision:
    """critic 对失败的判定。runner 据此决定是否再调一次 adapter。"""
    should_retry: bool
    hints: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


def _has_category(lessons: list[FailureLesson], cat: str) -> bool:
    return any(lesson.category == cat for lesson in lessons)


def derive_pre_hints(lessons: list[FailureLesson], *, tool: str) -> dict[str, Any]:
    """根据历史 lessons 派生"预防性" hints, 在首次调用前应用。"""
    hints: dict[str, Any] = {}
    if not lessons:
        return hints

    # 历史 rate_limit -> 预防性 backoff, 减小再次触发 429 的概率
    if _has_category(lessons, "rate_limit"):
        hints["backoff_ms"] = 2000

    # 历史 llm_api_error -> 轻微延迟以避免突发, 但不能修根本问题
    if _has_category(lessons, "llm_api_error"):
        hints.setdefault("retry_delay_ms", 1000)

    return hints


def decide_after_failure(
    *,
    error_category: str,
    lessons: list[FailureLesson],
    retries_used: int,
    max_retries: int = 1,
) -> CriticDecision:
    """根据本次失败类别 + 历史 lessons, 决定是否在重试预算内重试一次。"""
    if retries_used >= max_retries:
        return CriticDecision(False, {}, "retry budget exhausted")

    cat = error_category or "unknown"

    if cat == "rate_limit":
        return CriticDecision(
            True,
            {"backoff_ms": min(_MAX_BACKOFF_MS, 5000)},
            "rate_limit -> backoff and retry once",
        )

    if cat == "timeout":
        # task 级 timeout 由 runner 用 asyncio.wait_for 强制, adapter 无法在自己内部
        # 把它放大。只能加一点延迟后重试一次, 期望状态变好。
        return CriticDecision(
            True,
            {"retry_delay_ms": 1500},
            "timeout -> brief delay and retry once",
        )

    if cat == "llm_api_error":
        # 命中已知不可修 bug 时不重试, 避免浪费 token
        # 启发式: 历史 lesson 的根因里同时提到 "description" 与 "200" -> MiniMax schema 长度 bug
        known_unfixable = any(
            ("description" in lesson.root_cause_hypothesis
             and "200" in lesson.root_cause_hypothesis)
            for lesson in lessons
        )
        if known_unfixable:
            return CriticDecision(
                False, {},
                "llm_api_error matches known unfixable pattern (MiniMax 200-char schema bug); abort",
            )
        return CriticDecision(
            True,
            {"retry_delay_ms": min(_MAX_RETRY_DELAY_MS, 2000)},
            "llm_api_error (transient) -> delay and retry once",
        )

    if cat == "network":
        return CriticDecision(
            True,
            {"retry_delay_ms": 1000},
            "network blip -> brief delay and retry once",
        )

    if cat == "empty_extraction":
        # 没有 prompt 级的 hint 通道, 重试只会复读同样的失败, 跳过
        return CriticDecision(False, {}, "empty_extraction: no actionable hint, abort")

    return CriticDecision(False, {}, f"unhandled category {cat!r}: no critic action")
