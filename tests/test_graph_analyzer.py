from __future__ import annotations

"""
ScholarMind - 图谱分析与学习路径测试
=======================================

测试覆盖：
1. ConceptImportance 计算
2. 知识盲区检测（3 种类型）
3. 学习路径生成
4. 图谱健康度评估
5. 空图谱 / 单节点 / 聚焦领域 的边界情况
"""

import pytest

from src.knowledge.schema import NodeType, RelationType, KGNode, KGEdge
from src.knowledge.graph_store import KnowledgeGraphStore
from src.knowledge.graph_analyzer import (
    KnowledgeGraphAnalyzer,
    ConceptImportance,
    KnowledgeGap,
    LearningPathResult,
)


# ============================================================
# Fixtures
# ============================================================

def _build_sample_graph() -> KnowledgeGraphStore:
    """
    构建一个有代表性的小型知识图谱用于测试

    结构（ISAC 领域）：
    Paper1 --PROPOSES--> OFDM_Sensing (Method)
    Paper1 --USES-->     OFDM (Concept, 核心)
    Paper1 --USES-->     MIMO (Concept, 核心)
    Paper2 --PROPOSES--> Beam_Tracking (Method)
    Paper2 --USES-->     MIMO (Concept)
    Paper2 --USES-->     Beamforming (Concept)
    OFDM_Sensing --USES--> OFDM (Concept)
    Beam_Tracking --USES--> Beamforming (Concept)
    Beam_Tracking --IMPROVES--> OFDM_Sensing (Method)
    Isolated_Concept (no edges, 孤立)
    """
    store = KnowledgeGraphStore()

    # 论文
    store.add_node(KGNode(label="ISAC OFDM Sensing Design", node_type=NodeType.PAPER,
                          properties={"year": "2024", "venue": "IEEE TWC"}))
    store.add_node(KGNode(label="Beam Tracking for 6G", node_type=NodeType.PAPER,
                          properties={"year": "2025", "venue": "IEEE JSAC"}))

    # 核心概念
    store.add_node(KGNode(label="OFDM", node_type=NodeType.CONCEPT,
                          properties={"definition": "Orthogonal Frequency Division Multiplexing"}))
    store.add_node(KGNode(label="MIMO", node_type=NodeType.CONCEPT,
                          properties={"definition": "Multiple Input Multiple Output"}))
    store.add_node(KGNode(label="Beamforming", node_type=NodeType.CONCEPT,
                          properties={}))  # 属性稀疏 → 可能触发 foundation_gap

    # 方法
    store.add_node(KGNode(label="OFDM Sensing", node_type=NodeType.METHOD,
                          properties={"description": "OFDM-based sensing method"}))
    store.add_node(KGNode(label="Beam Tracking", node_type=NodeType.METHOD,
                          properties={"description": "Adaptive beam tracking algorithm"},
                          source_paper="Beam Tracking for 6G"))

    # 孤立概念（用于测试 isolated_concept 盲区检测）
    store.add_node(KGNode(label="RIS", node_type=NodeType.CONCEPT,
                          properties={}))

    # 关系
    edges = [
        ("ISAC OFDM Sensing Design", "OFDM Sensing", RelationType.PROPOSES),
        ("ISAC OFDM Sensing Design", "OFDM", RelationType.USES),
        ("ISAC OFDM Sensing Design", "MIMO", RelationType.USES),
        ("Beam Tracking for 6G", "Beam Tracking", RelationType.PROPOSES),
        ("Beam Tracking for 6G", "MIMO", RelationType.USES),
        ("Beam Tracking for 6G", "Beamforming", RelationType.USES),
        ("OFDM Sensing", "OFDM", RelationType.USES),
        ("Beam Tracking", "Beamforming", RelationType.USES),
        ("Beam Tracking", "OFDM Sensing", RelationType.IMPROVES),
    ]
    for src_label, tgt_label, rel in edges:
        src_node = [n for n in store._nodes.values() if n.label == src_label][0]
        tgt_node = [n for n in store._nodes.values() if n.label == tgt_label][0]
        store.add_edge(KGEdge(
            source_id=src_node.node_id,
            target_id=tgt_node.node_id,
            relation_type=rel,
        ))

    return store


@pytest.fixture
def sample_store():
    return _build_sample_graph()


@pytest.fixture
def analyzer(sample_store):
    return KnowledgeGraphAnalyzer(sample_store)


@pytest.fixture
def empty_analyzer():
    return KnowledgeGraphAnalyzer(KnowledgeGraphStore())


# ============================================================
# Tests: 空图谱边界
# ============================================================

class TestEmptyGraph:

    def test_empty_importance(self, empty_analyzer):
        result = empty_analyzer.compute_importance()
        assert result == []

    def test_empty_health(self, empty_analyzer):
        health = empty_analyzer.get_graph_health()
        assert health["总节点数"] == 0
        assert "空图谱" in health["健康等级"]

    def test_empty_gaps(self, empty_analyzer):
        gaps = empty_analyzer.detect_knowledge_gaps()
        assert gaps == []

    def test_empty_learning_path(self, empty_analyzer):
        result = empty_analyzer.generate_learning_path()
        assert isinstance(result, LearningPathResult)
        assert result.path == []
        assert result.gaps == []


# ============================================================
# Tests: 重要性计算
# ============================================================

class TestImportance:

    def test_all_nodes_scored(self, analyzer, sample_store):
        result = analyzer.compute_importance()
        assert len(result) == sample_store.node_count

    def test_sorted_by_importance(self, analyzer):
        result = analyzer.compute_importance()
        scores = [r.importance_score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_ofdm_and_mimo_high_importance(self, analyzer):
        """OFDM 和 MIMO 被最多节点引用，应该排名靠前"""
        result = analyzer.compute_importance()
        top_labels = [r.label for r in result[:4]]
        # OFDM 和 MIMO 至少应该在前 4 名（它们入度最高）
        assert "OFDM" in top_labels or "MIMO" in top_labels

    def test_importance_has_pagerank(self, analyzer):
        result = analyzer.compute_importance()
        for r in result:
            assert r.pagerank >= 0.0

    def test_importance_has_degree(self, analyzer):
        result = analyzer.compute_importance()
        for r in result:
            assert r.degree >= 0


# ============================================================
# Tests: 图谱健康度
# ============================================================

class TestGraphHealth:

    def test_health_has_all_fields(self, analyzer):
        health = analyzer.get_graph_health()
        assert "总节点数" in health
        assert "总关系数" in health
        assert "健康等级" in health
        assert "建议" in health

    def test_health_node_count(self, analyzer, sample_store):
        health = analyzer.get_graph_health()
        assert health["总节点数"] == sample_store.node_count

    def test_health_edge_count(self, analyzer, sample_store):
        health = analyzer.get_graph_health()
        assert health["总关系数"] == sample_store.edge_count


# ============================================================
# Tests: 知识盲区检测
# ============================================================

class TestKnowledgeGaps:

    def test_detects_isolated_concept(self, analyzer):
        """RIS 是孤立节点，应该被检测为盲区"""
        gaps = analyzer.detect_knowledge_gaps()
        isolated = [g for g in gaps if g.gap_type == "isolated_concept"]
        isolated_labels = [g.label for g in isolated]
        assert "RIS" in isolated_labels

    def test_gap_has_severity(self, analyzer):
        gaps = analyzer.detect_knowledge_gaps()
        for gap in gaps:
            assert 0.0 <= gap.severity <= 1.0

    def test_gap_has_suggestion(self, analyzer):
        gaps = analyzer.detect_knowledge_gaps()
        for gap in gaps:
            assert gap.suggested_action
            assert len(gap.suggested_action) > 10

    def test_gaps_sorted_by_severity(self, analyzer):
        gaps = analyzer.detect_knowledge_gaps()
        severities = [g.severity for g in gaps]
        assert severities == sorted(severities, reverse=True)


# ============================================================
# Tests: 学习路径生成
# ============================================================

class TestLearningPath:

    def test_generates_path(self, analyzer):
        result = analyzer.generate_learning_path()
        assert isinstance(result, LearningPathResult)
        assert len(result.path) > 0

    def test_path_excludes_papers_and_authors(self, analyzer):
        """学习路径不应该包含论文或作者节点"""
        result = analyzer.generate_learning_path()
        for item in result.path:
            assert item.node_type not in ("paper", "author")

    def test_path_has_sequential_order(self, analyzer):
        result = analyzer.generate_learning_path()
        orders = [item.order for item in result.path]
        assert orders == list(range(1, len(orders) + 1))

    def test_path_has_priority(self, analyzer):
        result = analyzer.generate_learning_path()
        valid_priorities = {"critical", "important", "supplementary"}
        for item in result.path:
            assert item.priority in valid_priorities

    def test_path_respects_max_items(self, analyzer):
        result = analyzer.generate_learning_path(max_items=3)
        assert len(result.path) <= 3

    def test_path_with_focus_area(self, analyzer):
        """聚焦 beamforming 应该过滤出相关概念"""
        result = analyzer.generate_learning_path(focus_area="beam")
        if result.path:
            labels = [item.label.lower() for item in result.path]
            # 至少一个条目应该跟 beam 相关
            assert any("beam" in label for label in labels)

    def test_result_includes_health(self, analyzer):
        result = analyzer.generate_learning_path()
        assert result.graph_health
        assert "总节点数" in result.graph_health

    def test_result_includes_gaps(self, analyzer):
        result = analyzer.generate_learning_path()
        assert isinstance(result.gaps, list)

    def test_to_markdown(self, analyzer):
        result = analyzer.generate_learning_path()
        md = result.to_markdown()
        assert "学习路径" in md
        assert "健康度" in md
        assert len(md) > 100
