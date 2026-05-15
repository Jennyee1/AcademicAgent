from __future__ import annotations

"""
其余能力指标 —— 图谱查询 / 盲区检测 / 代码执行 / 图表分析。

全部为纯函数，输入为 dict（task_result.raw 的字段）+ gold dict。
"""

from ..schema import MetricResult


def _norm(s: str) -> str:
    return " ".join(str(s).strip().lower().split())


def _norm_set(items: list) -> set:
    return {_norm(x) for x in (items or []) if x}


# ------------------------------------------------------------------ #
# 图谱查询
# ------------------------------------------------------------------ #

def query_hit_rate(
    matched_labels: list[str],
    expected_labels: list[str],
    task_id: str | None = None,
) -> MetricResult:
    """查询返回结果是否覆盖期望节点：命中的期望标签数 / 期望标签总数。"""
    exp = _norm_set(expected_labels)
    if not exp:
        return MetricResult(metric="query_hit_rate", value=0.0, task_id=task_id,
                            numerator=0, denominator=0, notes="empty expected set")
    got = _norm_set(matched_labels)
    hits = exp & got
    return MetricResult(
        metric="query_hit_rate", value=len(hits) / len(exp), task_id=task_id,
        numerator=float(len(hits)), denominator=float(len(exp)),
    )


def neighbor_recall(
    returned_neighbors: list[str],
    expected_neighbors: list[str],
    task_id: str | None = None,
) -> MetricResult:
    """get_related_concepts 返回的邻居对期望邻居的召回率。"""
    exp = _norm_set(expected_neighbors)
    if not exp:
        return MetricResult(metric="neighbor_recall", value=0.0, task_id=task_id,
                            numerator=0, denominator=0, notes="empty expected set")
    got = _norm_set(returned_neighbors)
    hits = exp & got
    return MetricResult(
        metric="neighbor_recall", value=len(hits) / len(exp), task_id=task_id,
        numerator=float(len(hits)), denominator=float(len(exp)),
    )


# ------------------------------------------------------------------ #
# 盲区检测
# ------------------------------------------------------------------ #

def gap_type_match(
    detected_gap_types: list[str],
    expected_gap_types: list[str],
    task_id: str | None = None,
) -> MetricResult:
    """检测出的盲区类型集合对期望类型的覆盖率（seed graph 是固定 fixture，故确定性）。"""
    exp = _norm_set(expected_gap_types)
    if not exp:
        return MetricResult(metric="gap_type_match", value=0.0, task_id=task_id,
                            numerator=0, denominator=0, notes="empty expected set")
    got = _norm_set(detected_gap_types)
    hits = exp & got
    return MetricResult(
        metric="gap_type_match", value=len(hits) / len(exp), task_id=task_id,
        numerator=float(len(hits)), denominator=float(len(exp)),
    )


def gap_label_recall(
    detected_gap_labels: list[str],
    expected_gap_labels: list[str],
    task_id: str | None = None,
) -> MetricResult:
    """检测出的盲区涉及的节点标签对期望标签的召回率。"""
    exp = _norm_set(expected_gap_labels)
    if not exp:
        return MetricResult(metric="gap_label_recall", value=0.0, task_id=task_id,
                            numerator=0, denominator=0, notes="empty expected set")
    got = _norm_set(detected_gap_labels)
    hits = exp & got
    return MetricResult(
        metric="gap_label_recall", value=len(hits) / len(exp), task_id=task_id,
        numerator=float(len(hits)), denominator=float(len(exp)),
    )


def top_concept_overlap(
    detected_top_concepts: list[str],
    expected_top_concepts: list[str],
    task_id: str | None = None,
) -> MetricResult:
    """importance 排序的 top 概念与期望 top 概念的重叠率。"""
    exp = _norm_set(expected_top_concepts)
    if not exp:
        return MetricResult(metric="top_concept_overlap", value=0.0, task_id=task_id,
                            numerator=0, denominator=0, notes="empty expected set")
    got = _norm_set(detected_top_concepts)
    hits = exp & got
    return MetricResult(
        metric="top_concept_overlap", value=len(hits) / len(exp), task_id=task_id,
        numerator=float(len(hits)), denominator=float(len(exp)),
    )


# ------------------------------------------------------------------ #
# 代码执行
# ------------------------------------------------------------------ #

def code_success_rate(
    success: bool,
    expect_success: bool = True,
    task_id: str | None = None,
) -> MetricResult:
    """代码执行结果与期望是否一致（1.0 = 一致）。"""
    value = 1.0 if bool(success) == bool(expect_success) else 0.0
    return MetricResult(
        metric="code_success_rate", value=value, task_id=task_id,
        numerator=value, denominator=1.0,
        notes=f"success={success}, expected={expect_success}",
    )


def stdout_assertion_pass(
    stdout: str,
    expect_contains: list[str],
    task_id: str | None = None,
) -> MetricResult:
    """stdout 包含所有期望子串的比例。"""
    needles = [str(x) for x in (expect_contains or [])]
    if not needles:
        return MetricResult(metric="stdout_assertion_pass", value=1.0, task_id=task_id,
                            numerator=0, denominator=0, notes="no assertions")
    text = str(stdout or "").lower()
    hits = sum(1 for n in needles if n.lower() in text)
    return MetricResult(
        metric="stdout_assertion_pass", value=hits / len(needles), task_id=task_id,
        numerator=float(hits), denominator=float(len(needles)),
    )


def artifact_produced_rate(
    output_files: list[str],
    expect_artifact: bool = False,
    task_id: str | None = None,
) -> MetricResult:
    """是否按期望产出了文件（图表等）。expect_artifact=False 时恒为 1.0。"""
    if not expect_artifact:
        return MetricResult(metric="artifact_produced_rate", value=1.0, task_id=task_id,
                            numerator=0, denominator=0, notes="artifact not expected")
    value = 1.0 if output_files else 0.0
    return MetricResult(
        metric="artifact_produced_rate", value=value, task_id=task_id,
        numerator=value, denominator=1.0,
        notes=f"{len(output_files or [])} files produced",
    )


# ------------------------------------------------------------------ #
# 图表分析
# ------------------------------------------------------------------ #

def figure_type_accuracy(
    figure_type: str,
    expect_figure_type: str,
    task_id: str | None = None,
) -> MetricResult:
    """图表类型分类是否正确。"""
    value = 1.0 if _norm(figure_type) == _norm(expect_figure_type) else 0.0
    return MetricResult(
        metric="figure_type_accuracy", value=value, task_id=task_id,
        numerator=value, denominator=1.0,
        notes=f"got={figure_type}, expected={expect_figure_type}",
    )


def figure_entity_recall(
    entities: list[str],
    expect_entities_contains: list[str],
    task_id: str | None = None,
) -> MetricResult:
    """图表中抽取的实体对期望实体的召回率。"""
    exp = _norm_set(expect_entities_contains)
    if not exp:
        return MetricResult(metric="figure_entity_recall", value=1.0, task_id=task_id,
                            numerator=0, denominator=0, notes="no expected entities")
    got = _norm_set(entities)
    hits = sum(1 for e in exp if any(e in g or g in e for g in got))
    return MetricResult(
        metric="figure_entity_recall", value=hits / len(exp), task_id=task_id,
        numerator=float(hits), denominator=float(len(exp)),
    )
