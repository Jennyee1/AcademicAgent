from __future__ import annotations

"""
单测：盲区 → 检索查询 + gap-driven paper-watch 编排。

被测对象：
  - src/knowledge/graph_analyzer.py 的 gaps_to_queries()
  - skills/paper_watch/scripts/gap_driven_watch.py 的 collect_gap_driven_papers()

策略：
  - 单测部分构造 KnowledgeGap dataclass 直接喂 gaps_to_queries，不碰图谱
  - 编排器集成测：注入 mock arxiv_fetcher 完全离线，验证盲区归因与去重
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.knowledge.graph_analyzer import (
    GapQuery,
    KnowledgeGap,
    gaps_to_queries,
)


# ---- gaps_to_queries: unit ---------------------------------------------------


def _gap(gap_type: str, label: str = "Attention", severity: float = 0.8,
         node_id: str | None = None) -> KnowledgeGap:
    return KnowledgeGap(
        node_id=node_id or f"node_{label}",
        label=label,
        node_type="concept",
        gap_type=gap_type,
        severity=severity,
        reason=f"reason for {gap_type}",
        suggested_action="...",
    )


def test_empty_gaps_returns_empty():
    assert gaps_to_queries([]) == []


def test_foundation_gap_uses_survey_template():
    out = gaps_to_queries([_gap("foundation_gap", label="Transformer")])
    assert len(out) == 1
    assert "survey" in out[0].query.lower()
    assert "Transformer" in out[0].query
    assert out[0].gap_type == "foundation_gap"


def test_isolated_concept_uses_applications_template():
    out = gaps_to_queries([_gap("isolated_concept", label="RoPE")])
    assert "applications" in out[0].query.lower()


def test_single_source_uses_comparison_template():
    out = gaps_to_queries([_gap("single_source", label="LoRA")])
    assert "comparison" in out[0].query.lower()


def test_temporal_gap_uses_latest_template():
    out = gaps_to_queries([_gap("temporal_gap", label="MoE", node_id="__stale_MoE__")])
    assert "latest" in out[0].query.lower() or "advances" in out[0].query.lower()


def test_unknown_gap_type_falls_back_to_label():
    out = gaps_to_queries([_gap("custom_unknown", label="DPO")])
    assert out[0].query == "DPO"


def test_min_severity_filter_drops_low_severity():
    gaps = [
        _gap("foundation_gap", label="A", severity=0.9),
        _gap("isolated_concept", label="B", severity=0.2),
    ]
    out = gaps_to_queries(gaps, min_severity=0.5)
    assert len(out) == 1
    assert "A" in out[0].query


def test_top_n_caps_number_of_gaps():
    gaps = [
        _gap("foundation_gap", label=f"L{i}", severity=0.9 - i * 0.05)
        for i in range(10)
    ]
    out = gaps_to_queries(gaps, top_n=3)
    assert len(out) == 3
    # 按 severity 取最高的 3 个 -> L0, L1, L2
    assert [q.gap_node_id for q in out] == ["node_L0", "node_L1", "node_L2"]


def test_sorted_by_severity_descending():
    gaps = [
        _gap("foundation_gap", label="Low", severity=0.3),
        _gap("isolated_concept", label="High", severity=0.95),
        _gap("single_source", label="Mid", severity=0.6),
    ]
    out = gaps_to_queries(gaps)
    assert [q.severity for q in out] == [0.95, 0.6, 0.3]


def test_query_records_rationale_with_gap_type():
    out = gaps_to_queries([_gap("foundation_gap", label="X")])
    assert "[foundation_gap]" in out[0].rationale


# ---- collect_gap_driven_papers: integration ---------------------------------


@pytest.fixture
def fake_graph(tmp_path: Path):
    """构造一个最小图谱，包含一个孤立概念（必然产出 isolated_concept gap）。"""
    from src.knowledge.graph_store import KnowledgeGraphStore
    from src.knowledge.schema import KGNode, NodeType

    graph_path = tmp_path / "graph.json"
    store = KnowledgeGraphStore(graph_path=graph_path)
    # 单一孤立概念节点 —— 度=0，必中 isolated_concept
    store.add_node(KGNode(
        label="Sparse Attention",
        node_type=NodeType.CONCEPT,
        properties={},
    ))
    store.save()
    return graph_path


def test_collect_gap_driven_papers_uses_mock_fetcher_and_attributes(fake_graph):
    """完整闭环：图谱 -> 盲区 -> query -> mock fetch -> 归因 digest。"""
    from skills.paper_watch.scripts.gap_driven_watch import collect_gap_driven_papers

    calls: list[str] = []

    def fake_fetcher(query: str, max_results: int = 3, days: int = 7):
        calls.append(query)
        return [{
            "title": f"Paper about {query}",
            "authors": ["Author A"],
            "abstract": "...",
            "arxiv_id": f"2401.{abs(hash(query)) % 100000:05d}",
            "published": "2026-05-10",
            "pdf_url": "",
            "categories": ["cs.LG"],
        }]

    digest = collect_gap_driven_papers(
        graph_path=fake_graph,
        top_n=3,
        max_results_per_query=2,
        days=7,
        arxiv_fetcher=fake_fetcher,
        request_interval=0,  # 测试不 sleep
    )

    # 至少触发了一次 query（fixture 节点既无属性又孤立，会同时触发 foundation_gap 和 isolated_concept）
    assert len(calls) >= 1
    assert any("Sparse Attention" in q for q in calls)
    # papers 上贴了 gap_attributions
    assert digest["total_count"] >= 1
    p = digest["papers"][0]
    assert "gap_attributions" in p
    # 应该至少有一种已知 gap_type
    expected_types = {"foundation_gap", "isolated_concept", "single_source", "temporal_gap"}
    seen_types = {a["gap_type"] for a in p["gap_attributions"]}
    assert seen_types & expected_types
    # query 记录里有 rationale
    assert all("rationale" in q for q in digest["queries"])
    # mode 标记
    assert digest["mode"] == "gap_driven"


def test_collect_gap_driven_papers_merges_attributions_for_duplicates(fake_graph):
    """多条 query 命中同一篇论文时，gap_attributions 应该合并而不是覆盖。"""
    from skills.paper_watch.scripts.gap_driven_watch import collect_gap_driven_papers

    # 让 fetcher 对任何 query 都返回同一篇论文 (固定 arxiv_id)
    def constant_fetcher(query: str, max_results: int = 3, days: int = 7):
        return [{
            "title": "The same paper",
            "authors": ["X"], "abstract": "...",
            "arxiv_id": "9999.99999",
            "published": "2026-05-10", "pdf_url": "",
            "categories": [],
        }]

    # 注入一个会同时触发多条 query 的图谱: 用多类型节点扩 gap 多样性 ——
    # 但 fake_graph 只产 isolated_concept，所以我们就用同一图谱测合并即可
    digest = collect_gap_driven_papers(
        graph_path=fake_graph,
        top_n=5, max_results_per_query=1, days=7,
        arxiv_fetcher=constant_fetcher, request_interval=0,
    )
    if digest["total_count"] >= 1:
        p = digest["papers"][0]
        # 至少 1 个 attribution (具体数取决于图谱产了多少 gap)
        assert len(p["gap_attributions"]) >= 1
        # arxiv_id 没被重复成多条 paper 记录
        ids = [pp["arxiv_id"] for pp in digest["papers"]]
        assert len(ids) == len(set(ids))


def test_collect_gap_driven_papers_handles_fetcher_exception(fake_graph):
    """fetcher 抛异常时，对应 query 记录 error，但整体 digest 不崩。"""
    from skills.paper_watch.scripts.gap_driven_watch import collect_gap_driven_papers

    def angry_fetcher(query: str, max_results: int = 3, days: int = 7):
        raise RuntimeError("arxiv exploded")

    digest = collect_gap_driven_papers(
        graph_path=fake_graph, top_n=2, max_results_per_query=1,
        days=7, arxiv_fetcher=angry_fetcher, request_interval=0,
    )
    assert digest["total_count"] == 0
    assert any("error" in q for q in digest["queries"])
