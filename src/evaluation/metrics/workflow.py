from __future__ import annotations

"""
L2 工作流指标 —— 完成率 / 工具序列匹配 / 步骤成功率 / 最终断言通过率。
"""

from ..schema import MetricResult


def workflow_completion_rate(
    all_steps_ok: bool,
    task_id: str | None = None,
) -> MetricResult:
    """整条工作流是否所有步骤都成功（1.0 = 完整跑通）。"""
    value = 1.0 if all_steps_ok else 0.0
    return MetricResult(
        metric="workflow_completion_rate", value=value, task_id=task_id,
        numerator=value, denominator=1.0,
    )


def tool_sequence_match(
    actual_sequence: list[str],
    expected_sequence: list[str],
    task_id: str | None = None,
) -> MetricResult:
    """实际工具调用序列与期望序列的逐位匹配率。"""
    expected = [str(x) for x in (expected_sequence or [])]
    actual = [str(x) for x in (actual_sequence or [])]
    if not expected:
        return MetricResult(metric="tool_sequence_match", value=0.0, task_id=task_id,
                            numerator=0, denominator=0, notes="empty expected sequence")
    matches = sum(
        1 for i, exp in enumerate(expected)
        if i < len(actual) and actual[i] == exp
    )
    return MetricResult(
        metric="tool_sequence_match", value=matches / len(expected), task_id=task_id,
        numerator=float(matches), denominator=float(len(expected)),
        notes=f"actual={actual}",
    )


def step_success_rate(
    step_ok_flags: list[bool],
    task_id: str | None = None,
) -> MetricResult:
    """工作流各步骤成功的占比。"""
    flags = list(step_ok_flags or [])
    if not flags:
        return MetricResult(metric="step_success_rate", value=0.0, task_id=task_id,
                            numerator=0, denominator=0, notes="no steps")
    ok = sum(1 for f in flags if f)
    return MetricResult(
        metric="step_success_rate", value=ok / len(flags), task_id=task_id,
        numerator=float(ok), denominator=float(len(flags)),
    )


def final_assertion_pass(
    assertion_results: list[bool],
    task_id: str | None = None,
) -> MetricResult:
    """工作流终态断言通过的占比（sidecar 最终状态是否符合期望）。"""
    results = list(assertion_results or [])
    if not results:
        return MetricResult(metric="final_assertion_pass", value=1.0, task_id=task_id,
                            numerator=0, denominator=0, notes="no final assertions")
    passed = sum(1 for r in results if r)
    return MetricResult(
        metric="final_assertion_pass", value=passed / len(results), task_id=task_id,
        numerator=float(passed), denominator=float(len(results)),
    )
