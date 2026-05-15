from __future__ import annotations

"""
检索能力指标 —— Recall@k / Precision@k / MRR / nDCG@k。

匹配优先用外部 ID（paper_id），其次用归一化标题。大小写不敏感。
"""

import math

from ..schema import MetricResult


def _normalize(s: str) -> str:
    return " ".join(str(s).strip().lower().split())


def _match_set(retrieved: list[str], gold: list[str]) -> tuple[list[bool], set[str]]:
    """返回 (retrieved 每项是否命中, 归一化 gold 集合)。"""
    gold_norm = {_normalize(g) for g in gold if g}
    hits = [_normalize(r) in gold_norm for r in retrieved]
    return hits, gold_norm


def recall_at_k(
    retrieved: list[str],
    gold: list[str],
    k: int = 5,
    task_id: str | None = None,
) -> MetricResult:
    """Recall@k = top-k 中命中的不同 gold 数 / gold 总数。"""
    metric = f"recall_at_{k}"
    if not gold:
        return MetricResult(metric=metric, value=0.0, task_id=task_id,
                            numerator=0, denominator=0, notes="empty gold set")
    _, gold_norm = _match_set(retrieved[:k], gold)
    top_k_norm = {_normalize(r) for r in retrieved[:k]}
    hit_set = top_k_norm & gold_norm
    return MetricResult(
        metric=metric, value=len(hit_set) / len(gold_norm), task_id=task_id,
        numerator=float(len(hit_set)), denominator=float(len(gold_norm)),
    )


def precision_at_k(
    retrieved: list[str],
    gold: list[str],
    k: int = 5,
    task_id: str | None = None,
) -> MetricResult:
    """Precision@k = top-k 中命中数 / k。"""
    metric = f"precision_at_{k}"
    if k <= 0:
        return MetricResult(metric=metric, value=0.0, task_id=task_id,
                            numerator=0, denominator=0, notes="k<=0")
    hits, _ = _match_set(retrieved[:k], gold)
    hit_count = sum(hits)
    return MetricResult(
        metric=metric, value=hit_count / k, task_id=task_id,
        numerator=float(hit_count), denominator=float(k),
    )


def mrr(
    retrieved: list[str],
    gold: list[str],
    task_id: str | None = None,
) -> MetricResult:
    """首个 gold 命中的倒数排名。无命中返回 0.0。"""
    gold_norm = {_normalize(g) for g in gold if g}
    for rank, item in enumerate(retrieved, start=1):
        if _normalize(item) in gold_norm:
            return MetricResult(
                metric="mrr", value=1.0 / rank, task_id=task_id,
                numerator=1.0, denominator=float(rank),
                notes=f"first hit at rank {rank}",
            )
    return MetricResult(
        metric="mrr", value=0.0, task_id=task_id,
        numerator=0, denominator=float(len(retrieved)),
        notes="no gold item found",
    )


def ndcg_at_k(
    retrieved: list[str],
    gold: list[str],
    k: int = 5,
    task_id: str | None = None,
) -> MetricResult:
    """nDCG@k，二元相关性（命中=1）。"""
    metric = f"ndcg_at_{k}"
    gold_norm = {_normalize(g) for g in gold if g}
    if not gold_norm:
        return MetricResult(metric=metric, value=0.0, task_id=task_id,
                            numerator=0, denominator=0, notes="empty gold set")
    dcg = 0.0
    for i, item in enumerate(retrieved[:k]):
        if _normalize(item) in gold_norm:
            dcg += 1.0 / math.log2(i + 2)
    ideal_hits = min(len(gold_norm), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    value = dcg / idcg if idcg > 0 else 0.0
    return MetricResult(
        metric=metric, value=value, task_id=task_id,
        numerator=round(dcg, 4), denominator=round(idcg, 4),
    )
