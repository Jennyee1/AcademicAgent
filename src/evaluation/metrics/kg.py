from __future__ import annotations

"""
知识图谱抽取指标 —— 节点 F1 / 边 F1 / Schema 合法率 / 非空抽取率。

输入为 dict 列表（KGNode.to_dict() / KGEdge.to_dict() 的产物），
不依赖业务对象，便于离线复现与单测。
"""

import json
import re

from ..schema import MetricResult


def _normalize_label(label: str) -> str:
    """与 src/knowledge/schema.py KGNode._normalize_label 一致：
    小写 + 去特殊字符 + 空格转下划线。"""
    label = str(label).lower().strip()
    label = re.sub(r"[^a-z0-9\s一-鿿]", "", label)
    label = re.sub(r"\s+", "_", label)
    return label


def _node_key(label: str, node_type: str) -> tuple[str, str]:
    return (_normalize_label(label), str(node_type).strip().lower())


def _label_from_node_id(node_id: str) -> str:
    """node_id 形如 "{type}_{normalized_label}"，取后半。"""
    parts = str(node_id).split("_", 1)
    return parts[1] if len(parts) == 2 else str(node_id)


def _edge_key(src_label: str, rel_type: str, tgt_label: str) -> tuple[str, str, str]:
    def _norm(s: str) -> str:
        return _normalize_label(str(s).replace("_", " "))
    return (_norm(src_label), str(rel_type).strip().lower(), _norm(tgt_label))


def _prf(tp: int, n_pred: int, n_gold: int) -> tuple[float, float, float]:
    precision = tp / n_pred if n_pred else 0.0
    recall = tp / n_gold if n_gold else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def kg_node_f1(
    extracted_nodes: list[dict],
    gold_nodes: list[dict],
    task_id: str | None = None,
) -> MetricResult:
    """(归一化 label, node_type) 对的 F1。

    extracted_nodes : [{"label", "node_type", ...}]
    gold_nodes      : [{"label", "node_type"}]
    """
    ext_keys = {
        _node_key(n.get("label", ""), n.get("node_type", ""))
        for n in extracted_nodes
    }
    gold_keys = {
        _node_key(g.get("label", ""), g.get("node_type", ""))
        for g in gold_nodes
    }
    if not gold_keys and not ext_keys:
        return MetricResult(metric="kg_node_f1", value=1.0, task_id=task_id,
                            numerator=0, denominator=0,
                            notes='{"precision":1.0,"recall":1.0}')
    tp = len(ext_keys & gold_keys)
    p, r, f1 = _prf(tp, len(ext_keys), len(gold_keys))
    return MetricResult(
        metric="kg_node_f1", value=f1, task_id=task_id,
        numerator=float(tp), denominator=float(len(gold_keys)),
        notes=json.dumps({"precision": round(p, 4), "recall": round(r, 4)}),
    )


def kg_edge_f1(
    extracted_edges: list[dict],
    gold_edges: list[dict],
    task_id: str | None = None,
) -> MetricResult:
    """(src_label, relation_type, tgt_label) 三元组的 F1。

    extracted_edges : [{"source_id", "target_id", "relation_type", ...}]
    gold_edges      : [{"source_label", "relation_type", "target_label"}]
    """
    ext_keys = set()
    for e in extracted_edges:
        src = e.get("source_label") or _label_from_node_id(e.get("source_id", ""))
        tgt = e.get("target_label") or _label_from_node_id(e.get("target_id", ""))
        ext_keys.add(_edge_key(src, e.get("relation_type", ""), tgt))
    gold_keys = {
        _edge_key(g.get("source_label", ""), g.get("relation_type", ""), g.get("target_label", ""))
        for g in gold_edges
    }
    if not gold_keys and not ext_keys:
        return MetricResult(metric="kg_edge_f1", value=1.0, task_id=task_id,
                            numerator=0, denominator=0,
                            notes='{"precision":1.0,"recall":1.0}')
    tp = len(ext_keys & gold_keys)
    p, r, f1 = _prf(tp, len(ext_keys), len(gold_keys))
    return MetricResult(
        metric="kg_edge_f1", value=f1, task_id=task_id,
        numerator=float(tp), denominator=float(len(gold_keys)),
        notes=json.dumps({"precision": round(p, 4), "recall": round(r, 4)}),
    )


# 合法 Schema 类型 —— 与 src/knowledge/schema.py 的 NodeType / RelationType 对齐。
# 优先动态读取（保证不漂移），import 失败时回退到硬编码常量，
# 使指标层不强依赖业务模块的传递依赖（如 pydantic）。
_FALLBACK_NODE_TYPES = {
    "paper", "author", "concept", "method", "dataset", "metric", "tool",
}
_FALLBACK_REL_TYPES = {
    "proposes", "uses", "improves", "extends", "compares_with", "cites",
    "authored_by", "evaluated_by", "belongs_to", "related_to", "tested_on",
}


def _valid_schema_types() -> tuple[set[str], set[str]]:
    try:
        from src.knowledge.schema import NodeType, RelationType
        return ({t.value for t in NodeType}, {t.value for t in RelationType})
    except Exception:  # noqa: BLE001 — 业务模块依赖缺失时回退
        return (set(_FALLBACK_NODE_TYPES), set(_FALLBACK_REL_TYPES))


def schema_validity_rate(
    extracted_nodes: list[dict],
    extracted_edges: list[dict],
    task_id: str | None = None,
) -> MetricResult:
    """抽取项中 node_type / relation_type 属于合法 Schema 枚举的占比。"""
    valid_node, valid_rel = _valid_schema_types()

    total = len(extracted_nodes) + len(extracted_edges)
    if total == 0:
        return MetricResult(metric="schema_validity_rate", value=1.0, task_id=task_id,
                            numerator=0, denominator=0, notes="no items to validate")
    valid = sum(1 for n in extracted_nodes if n.get("node_type") in valid_node)
    valid += sum(1 for e in extracted_edges if e.get("relation_type") in valid_rel)
    return MetricResult(
        metric="schema_validity_rate", value=valid / total, task_id=task_id,
        numerator=float(valid), denominator=float(total),
    )


def extraction_nonempty_rate(
    extracted_nodes: list[dict],
    extracted_edges: list[dict],
    task_id: str | None = None,
) -> MetricResult:
    """是否抽到了任何节点/边（1.0 = 非空）。

    与 schema_validity_rate（空时返回 1.0）互补：
    专门暴露「抽取静默失败、产出 0 节点」这种本应可见的问题。
    """
    nonempty = 1.0 if (extracted_nodes or extracted_edges) else 0.0
    return MetricResult(
        metric="extraction_nonempty_rate", value=nonempty, task_id=task_id,
        numerator=nonempty, denominator=1.0,
        notes=f"{len(extracted_nodes)} nodes, {len(extracted_edges)} edges",
    )
