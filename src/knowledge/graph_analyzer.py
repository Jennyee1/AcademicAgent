from __future__ import annotations

"""
ScholarMind - 知识图谱分析与学习路径规划
===========================================

基于知识图谱的结构分析，实现四大核心能力：
  1. 图谱结构分析（PageRank, 度分布, 连通分量）
  2. 知识盲区检测（稀疏区域 + 孤立概念 + 单源依赖 + 时代盲区）
  3. 学习路径推荐（拓扑排序 + 重要性加权 + 时间优先级）
  4. 双时态分析（知识时代分布 + 学习进度追踪 + 知识新鲜度）

【工程思考】为什么 Phase 3 在 Phase 2 之后？
  Phase 2 建好了知识图谱（节点 + 边），Phase 3 才能在上面做图分析。
  这就像先有了地图（Phase 2），才能做路径规划（Phase 3）。

【算法思考】PageRank 在学术知识图谱中的含义：
  - 原始 PageRank: 网页越多被引用，越重要
  - 我们的图谱: 被越多论文/方法引用或使用的概念，越是"核心基础概念"
  - 所以 PageRank 高的概念 = 应该优先学习的概念

【算法思考】知识盲区检测的数学定义：
  盲区 = 图谱中"你应该知道但不够了解"的区域
  具体量化指标：
  1. 入度高但出度低的概念 → 很多东西依赖它，但你没深入了解
  2. PageRank 高但属性稀疏的节点 → 重要但缺乏详细记录
  3. 连通分量的边缘节点 → 与主体知识连接弱
"""

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

import networkx as nx

from .schema import NodeType, RelationType, KGNode
from .graph_store import KnowledgeGraphStore

logger = logging.getLogger("ScholarMind.GraphAnalyzer")


# ============================================================
# 数据类
# ============================================================

@dataclass
class ConceptImportance:
    """概念重要性评分"""
    node_id: str
    label: str
    node_type: str
    pagerank: float = 0.0
    degree: int = 0
    in_degree: int = 0
    out_degree: int = 0
    betweenness: float = 0.0    # 介数中心性：处于多少条最短路径上
    recency_boost: float = 0.0  # 时间新鲜度加成（first_seen_year 越近越高）
    importance_score: float = 0.0  # 综合重要性评分


@dataclass
class KnowledgeGap:
    """
    知识盲区

    【工程思考】盲区有四种类型：
    1. foundation_gap: 基础概念掌握不够（PageRank 高但属性稀疏）
    2. isolated_concept: 孤立概念（与其他知识缺乏连接）
    3. single_source: 单一来源依赖（一个概念只从一篇论文了解）
    4. temporal_gap: 时代盲区（知识集中在某个年代，缺少新/旧方法的覆盖）
    """
    node_id: str
    label: str
    node_type: str
    gap_type: str          # foundation_gap | isolated_concept | single_source | temporal_gap
    severity: float        # 严重程度 0.0 ~ 1.0
    reason: str            # 人类可读的原因描述
    suggested_action: str  # 建议的学习行动


@dataclass
class TemporalAnalysis:
    """
    双时态分析结果

    利用 first_seen_year（有效时间）和 created_at（事务时间）
    分析用户的知识时代覆盖度、学习进度和知识新鲜度。
    """
    era_distribution: dict[str, int]    # {"pre-2015": 5, "2015-2019": 7, "2020+": 10, "unknown": 3}
    era_bias: str                       # "偏旧" | "均衡" | "偏新"
    freshness_score: float              # 0~1, 越高表示知识越前沿
    recent_focus_areas: list[str]       # 最近 7 天录入的概念方向
    stale_concepts: list[str]           # 重要但来自较旧年代的概念
    learning_velocity: dict[str, int]   # {"2026-05-06": 30, "2026-05-07": 15}
    avg_year: float                     # 有标注节点的平均年份
    year_span: tuple[int, int] | None   # (最早年份, 最新年份)


@dataclass
class LearningPathItem:
    """学习路径中的一个条目"""
    order: int             # 学习顺序（1 = 最先学）
    node_id: str
    label: str
    node_type: str
    priority: str          # critical / important / supplementary
    reason: str            # 为什么推荐学这个
    prerequisites: list[str] = field(default_factory=list)  # 前置概念
    related_papers: list[str] = field(default_factory=list)  # 相关论文


@dataclass
class LearningPathResult:
    """完整的学习路径推荐结果"""
    path: list[LearningPathItem] = field(default_factory=list)
    gaps: list[KnowledgeGap] = field(default_factory=list)
    graph_health: dict = field(default_factory=dict)

    def to_markdown(self) -> str:
        """生成 Markdown 格式的学习路径报告"""
        lines = ["## 🎯 个性化学习路径\n"]

        # 图谱健康度
        lines.append("### 📊 知识图谱健康度\n")
        lines.append("| 指标 | 值 |")
        lines.append("|:---|:---|")
        for k, v in self.graph_health.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

        # 知识盲区
        if self.gaps:
            lines.append(f"### ⚠️ 发现 {len(self.gaps)} 个知识盲区\n")
            for gap in self.gaps:
                severity_icon = "🔴" if gap.severity > 0.7 else "🟡" if gap.severity > 0.4 else "🟢"
                lines.append(
                    f"- {severity_icon} **{gap.label}** ({gap.node_type})\n"
                    f"  - 类型: {gap.gap_type}\n"
                    f"  - 原因: {gap.reason}\n"
                    f"  - 建议: {gap.suggested_action}\n"
                )
            lines.append("")

        # 学习路径
        lines.append("### 📚 推荐学习路径\n")
        lines.append("| 序号 | 概念 | 优先级 | 原因 |")
        lines.append("|:---|:---|:---|:---|")
        for item in self.path:
            priority_icon = {"critical": "🔴", "important": "🟡", "supplementary": "🟢"}.get(
                item.priority, "⚪"
            )
            prereqs = ", ".join(item.prerequisites[:3]) if item.prerequisites else "-"
            lines.append(
                f"| {item.order} | **{item.label}** ({item.node_type}) | "
                f"{priority_icon} {item.priority} | {item.reason} |"
            )
        lines.append("")

        # 详细路径说明
        if self.path:
            lines.append("### 📖 详细学习建议\n")
            for item in self.path[:10]:
                lines.append(f"#### {item.order}. {item.label}\n")
                lines.append(f"- **类型**: {item.node_type}")
                lines.append(f"- **优先级**: {item.priority}")
                lines.append(f"- **原因**: {item.reason}")
                if item.prerequisites:
                    lines.append(f"- **前置知识**: {', '.join(item.prerequisites)}")
                if item.related_papers:
                    lines.append(f"- **相关论文**: {', '.join(item.related_papers[:3])}")
                lines.append("")

        return "\n".join(lines)


class KnowledgeGraphAnalyzer:
    """
    知识图谱分析引擎

    Usage:
        store = KnowledgeGraphStore("data/knowledge_graph.json")
        analyzer = KnowledgeGraphAnalyzer(store)
        result = analyzer.generate_learning_path()
        print(result.to_markdown())

    【工程思考】为什么分析逻辑独立于 graph_store？
    1. 单一职责: graph_store 负责 CRUD，analyzer 负责分析
    2. 可测试性: 分析算法可以用构造好的图谱单独测试
    3. 可替换性: 未来迁移到 Neo4j 时，graph_store 变但 analyzer 接口不变
    """

    def __init__(self, store: KnowledgeGraphStore):
        self.store = store
        # 直接引用底层 networkx 图（只在分析时使用，不修改数据）
        self._graph = store._graph

    # ============================================================
    # 1. 图谱结构分析
    # ============================================================

    def compute_importance(self) -> list[ConceptImportance]:
        """
        计算所有节点的重要性评分

        综合 4 个指标：
        1. PageRank（全局重要性）
        2. 度中心性（直接连接数）
        3. 入度（被引用/使用次数）
        4. 介数中心性（知识桥梁作用）

        【算法细节】综合评分公式：
        importance = 0.4 * pagerank_norm + 0.3 * degree_norm + 0.2 * in_degree_norm + 0.1 * betweenness_norm

        为什么 PageRank 权重最高？
        因为学术知识图谱的核心是"被引用的重要性传递"，
        这和 PageRank 的原始设计思想完全吻合。
        """
        if not self._graph.nodes():
            return []

        # 计算各指标
        pagerank = nx.pagerank(self._graph, alpha=0.85)
        betweenness = nx.betweenness_centrality(self._graph)

        results = []
        for node_id in self._graph.nodes():
            node = self.store.get_node(node_id)
            if not node:
                continue

            in_deg = self._graph.in_degree(node_id)
            out_deg = self._graph.out_degree(node_id)
            degree = in_deg + out_deg

            results.append(ConceptImportance(
                node_id=node_id,
                label=node.label,
                node_type=node.node_type.value,
                pagerank=pagerank.get(node_id, 0.0),
                degree=degree,
                in_degree=in_deg,
                out_degree=out_deg,
                betweenness=betweenness.get(node_id, 0.0),
            ))

        # 计算 recency_boost
        current_year = datetime.now().year
        for r in results:
            node = self.store.get_node(r.node_id)
            if node and node.first_seen_year:
                # 2010 → 0.0, 2017 → 0.47, 2023 → 0.87, 2026 → 1.0
                r.recency_boost = min(1.0, max(0.0,
                    (node.first_seen_year - 2010) / max(1, current_year - 2010)
                ))
            else:
                r.recency_boost = 0.5  # 缺失时给中间值，不惩罚

        # 归一化并计算综合评分（含时间加权）
        #
        # 【算法变更】权重从 [0.4, 0.3, 0.2, 0.1] 变为 [0.35, 0.25, 0.15, 0.10, 0.15]
        # 新增 recency_boost 占 15%，让前沿方法在同等结构条件下排名略高
        if results:
            max_pr = max(r.pagerank for r in results) or 1.0
            max_deg = max(r.degree for r in results) or 1
            max_in = max(r.in_degree for r in results) or 1
            max_bt = max(r.betweenness for r in results) or 1.0

            for r in results:
                r.importance_score = (
                    0.35 * (r.pagerank / max_pr)
                    + 0.25 * (r.degree / max_deg)
                    + 0.15 * (r.in_degree / max_in)
                    + 0.10 * (r.betweenness / max_bt)
                    + 0.15 * r.recency_boost
                )

        results.sort(key=lambda r: r.importance_score, reverse=True)
        return results

    def get_graph_health(self) -> dict:
        """
        评估知识图谱的整体健康度

        【工程思考】"健康度"是一个复合指标，帮助用户理解：
        - 知识覆盖面够不够广？（节点数）
        - 知识之间的关联够不够密？（边密度）
        - 有没有孤立的知识岛？（连通分量数）
        - 知识深度够不够？（平均度）
        """
        n = self.store.node_count
        e = self.store.edge_count

        if n == 0:
            return {
                "总节点数": 0,
                "总关系数": 0,
                "健康等级": "⬜ 空图谱",
                "建议": "开始添加论文到知识图谱",
            }

        # 基础统计
        avg_degree = (2 * e) / n if n > 0 else 0
        density = nx.density(self._graph)
        components = nx.number_weakly_connected_components(self._graph)

        # 类型分布
        type_counts = Counter(
            node.node_type.value for node in self.store._nodes.values()
        )

        # 健康等级判定
        if n < 10:
            level = "🟡 起步阶段"
            advice = "继续添加论文，建议至少积累 5 篇论文的知识"
        elif n < 50 and avg_degree < 2:
            level = "🟡 知识稀疏"
            advice = "知识节点之间关联不够密集，建议精读论文提取更多关系"
        elif components > n * 0.3:
            level = "🟡 知识碎片化"
            advice = "存在多个孤立的知识岛，建议阅读综述论文建立跨领域连接"
        elif n >= 50 and avg_degree >= 3:
            level = "🟢 健康"
            advice = "知识图谱结构良好，可以开始做知识盲区分析"
        else:
            level = "🟢 良好"
            advice = "继续积累，关注高 PageRank 但了解不深的概念"

        return {
            "总节点数": n,
            "总关系数": e,
            "平均度": f"{avg_degree:.2f}",
            "图密度": f"{density:.4f}",
            "连通分量数": components,
            "节点类型分布": ", ".join(f"{t}:{c}" for t, c in type_counts.items()),
            "健康等级": level,
            "建议": advice,
        }

    # ============================================================
    # 2. 双时态分析
    # ============================================================

    def analyze_temporal(self) -> TemporalAnalysis:
        """
        基于双时态字段的综合分析

        利用两个独立时间轴：
        - first_seen_year（有效时间）：知识在现实中何时出现
        - created_at（事务时间）：知识何时被录入图谱

        分析三个维度：
        1. 知识时代分布 — 你的知识偏向哪个年代？
        2. 学习进度追踪 — 你最近在哪个方向发力？
        3. 知识新鲜度 — 你学的内容够新吗？
        """
        current_year = datetime.now().year

        # --- 1. 时代分布（基于 first_seen_year）---
        eras: dict[str, int] = {"pre-2015": 0, "2015-2019": 0, "2020+": 0, "unknown": 0}
        years: list[int] = []

        for node in self.store._nodes.values():
            if node.node_type in (NodeType.PAPER, NodeType.AUTHOR):
                continue  # 只分析 method / concept / metric / dataset
            y = node.first_seen_year
            if not y:
                eras["unknown"] += 1
            elif y < 2015:
                eras["pre-2015"] += 1
                years.append(y)
            elif y < 2020:
                eras["2015-2019"] += 1
                years.append(y)
            else:
                eras["2020+"] += 1
                years.append(y)

        # --- 2. 时代偏差判断 ---
        known_total = sum(v for k, v in eras.items() if k != "unknown")
        if known_total == 0:
            era_bias = "均衡"
            avg_year = 0.0
            year_span = None
        else:
            avg_year = sum(years) / len(years) if years else 0.0
            new_ratio = eras["2020+"] / known_total
            old_ratio = eras["pre-2015"] / known_total

            if new_ratio >= 0.6:
                era_bias = "偏新"
            elif old_ratio >= 0.4 and new_ratio < 0.3:
                era_bias = "偏旧"
            else:
                era_bias = "均衡"

            year_span = (min(years), max(years)) if years else None

        # --- 3. 知识新鲜度 ---
        # 归一化到 0~1：2010 → 0, current_year → 1
        if avg_year > 0:
            freshness = min(1.0, max(0.0,
                (avg_year - 2010) / max(1, current_year - 2010)
            ))
        else:
            freshness = 0.5  # 无数据时取中间值

        # --- 4. 学习进度（基于 created_at）---
        velocity: dict[str, int] = Counter()
        for node in self.store._nodes.values():
            if node.created_at:
                date_str = node.created_at[:10]  # YYYY-MM-DD
                velocity[date_str] += 1

        # --- 5. 最近关注方向（最近 7 天录入的概念）---
        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()[:10]
        recent_nodes = [
            node for node in self.store._nodes.values()
            if node.created_at and node.created_at[:10] >= seven_days_ago
            and node.node_type not in (NodeType.PAPER, NodeType.AUTHOR)
        ]
        # 按 source_paper 聚类
        focus_papers = Counter(n.source_paper for n in recent_nodes if n.source_paper)
        recent_focus = [paper for paper, _ in focus_papers.most_common(5)]

        # --- 6. 陈旧重要概念 ---
        # 重要性高（度 ≥ 3）但 first_seen_year 在 2018 之前的概念
        stale: list[str] = []
        for node_id, node in self.store._nodes.items():
            if (
                node.node_type in (NodeType.METHOD, NodeType.CONCEPT)
                and node.first_seen_year
                and node.first_seen_year < 2018
            ):
                degree = self._graph.in_degree(node_id) + self._graph.out_degree(node_id)
                if degree >= 3:
                    stale.append(node.label)

        return TemporalAnalysis(
            era_distribution=eras,
            era_bias=era_bias,
            freshness_score=freshness,
            recent_focus_areas=recent_focus,
            stale_concepts=stale,
            learning_velocity=dict(sorted(velocity.items())),
            avg_year=avg_year,
            year_span=year_span,
        )

    # ============================================================
    # 3. 知识盲区检测
    # ============================================================

    def detect_knowledge_gaps(self) -> list[KnowledgeGap]:
        """
        检测知识图谱中的盲区

        四种盲区类型：

        1. foundation_gap (基础缺失):
           - PageRank 高（是核心概念）但属性稀疏（没有详细记录定义/描述）
           - 说明你知道这个概念存在，但没有深入学习过

        2. isolated_concept (孤立概念):
           - 度 ≤ 1 且不是论文/作者类型
           - 说明这个知识点跟你其他知识没有建立联系

        3. single_source (单源依赖):
           - 一个概念只从一篇论文中了解（source_papers 只有 1 篇）
           - 说明你对这个概念的理解可能有偏见，需要交叉验证

        4. temporal_gap (时代盲区):
           - 利用 first_seen_year 检测知识是否集中在某个年代
           - 标记重要但来自较旧年代的概念（可能需要了解最新演进）

        【工程思考】为什么盲区检测很重要？
        - 学生读论文容易"只见树木不见森林"
        - 盲区检测帮助学生发现自己以为懂但其实不懂的概念
        - 这正是"主动学习路径规划"的核心价值
        """
        gaps = []
        importance = self.compute_importance()

        # 构建 PageRank 排名映射
        importance_map = {r.node_id: r for r in importance}

        for node_id, node in self.store._nodes.items():
            imp = importance_map.get(node_id)
            if not imp:
                continue

            # --- 类型 1: 基础缺失 ---
            # PageRank 排名在前 30%，但属性数量少
            if node.node_type in (NodeType.CONCEPT, NodeType.METHOD):
                pr_rank = importance.index(imp) if imp in importance else len(importance)
                is_top = pr_rank < len(importance) * 0.3
                prop_count = len([
                    v for v in node.properties.values()
                    if v and v != "" and v != []
                ])

                if is_top and prop_count < 2:
                    gaps.append(KnowledgeGap(
                        node_id=node_id,
                        label=node.label,
                        node_type=node.node_type.value,
                        gap_type="foundation_gap",
                        severity=min(1.0, imp.importance_score * 1.2),
                        reason=(
                            f"核心概念（PageRank 排名前 {int(pr_rank / len(importance) * 100)}%），"
                            f"但属性信息不足（仅 {prop_count} 条属性）"
                        ),
                        suggested_action=(
                            f"深入学习 {node.label}：阅读相关教材或综述论文，"
                            f"补充定义、核心公式、应用场景等信息"
                        ),
                    ))

            # --- 类型 2: 孤立概念 ---
            if (
                node.node_type not in (NodeType.PAPER, NodeType.AUTHOR)
                and imp.degree <= 1
            ):
                gaps.append(KnowledgeGap(
                    node_id=node_id,
                    label=node.label,
                    node_type=node.node_type.value,
                    gap_type="isolated_concept",
                    severity=0.5,
                    reason=(
                        f"与其他知识节点几乎没有连接（度={imp.degree}），"
                        f"可能是理解碎片化"
                    ),
                    suggested_action=(
                        f"探索 {node.label} 与其他概念的关系：它属于什么大类？"
                        f"跟哪些方法相关？在什么场景下使用？"
                    ),
                ))

            # --- 类型 3: 单源依赖 ---
            source_papers = node.properties.get("source_papers", [])
            if not source_papers and node.source_paper:
                source_papers = [node.source_paper]
            if (
                len(source_papers) == 1
                and node.node_type in (NodeType.CONCEPT, NodeType.METHOD)
                and imp.importance_score > 0.3
            ):
                gaps.append(KnowledgeGap(
                    node_id=node_id,
                    label=node.label,
                    node_type=node.node_type.value,
                    gap_type="single_source",
                    severity=0.4,
                    reason=(
                        f"仅从 1 篇论文了解（{source_papers[0][:40]}...），"
                        f"理解可能存在偏差"
                    ),
                    suggested_action=(
                        f"寻找关于 {node.label} 的其他论文或教材，"
                        f"交叉验证你的理解是否全面"
                    ),
                ))

        # --- 类型 4: 时代盲区 ---
        # 分析 first_seen_year 的分布，检测知识是否偏向某个时代
        temporal = self.analyze_temporal()
        if temporal.era_bias == "偏旧":
            gaps.append(KnowledgeGap(
                node_id="__temporal_bias__",
                label="知识时代偏差",
                node_type="temporal",
                gap_type="temporal_gap",
                severity=0.6,
                reason=(
                    f"知识偏向旧方法（平均年份 {temporal.avg_year:.0f}），"
                    f"2020+ 占比不足 40%。可能缺少最新研究进展"
                ),
                suggested_action=(
                    "建议阅读 2023-2024 年的最新论文，"
                    "补充前沿方法（如 Flash Attention, MoE, Agent Framework 等）"
                ),
            ))
        elif temporal.era_bias == "偏新":
            gaps.append(KnowledgeGap(
                node_id="__temporal_bias__",
                label="知识时代偏差",
                node_type="temporal",
                gap_type="temporal_gap",
                severity=0.4,
                reason=(
                    f"知识偏向新方法（平均年份 {temporal.avg_year:.0f}），"
                    f"缺少经典基础知识的覆盖"
                ),
                suggested_action=(
                    "建议补充经典基础论文（如 LSTM, ResNet, Word2Vec 等），"
                    "加深对领域演进脉络的理解"
                ),
            ))

        # 标记重要但年代较旧的概念
        if temporal.stale_concepts:
            for label in temporal.stale_concepts[:5]:
                gaps.append(KnowledgeGap(
                    node_id=f"__stale_{label}__",
                    label=label,
                    node_type="concept",
                    gap_type="temporal_gap",
                    severity=0.35,
                    reason=f"核心概念但来自较旧年代，可能需要了解其最新演进",
                    suggested_action=f"搜索 {label} 的最新改进或替代方法",
                ))

        # 按严重程度排序
        gaps.sort(key=lambda g: g.severity, reverse=True)
        logger.info(f"知识盲区检测完成: 发现 {len(gaps)} 个盲区")
        return gaps

    # ============================================================
    # 3. 学习路径推荐
    # ============================================================

    def generate_learning_path(
        self,
        focus_area: str = "",
        max_items: int = 15,
    ) -> LearningPathResult:
        """
        生成个性化学习路径

        Args:
            focus_area: 可选，聚焦的领域关键词（如 "agent memory"）
            max_items: 最大推荐条目数

        Returns:
            LearningPathResult: 包含学习路径、知识盲区、图谱健康度

        【算法思考】学习路径生成的核心逻辑：

        Step 1: 计算重要性 → 确定"应该学什么"
        Step 2: 检测盲区 → 确定"缺什么"
        Step 3: 拓扑排序 → 确定"先学什么"
        Step 4: 综合排序 → 生成最终路径

        综合排序公式：
        priority = importance_score * 0.4 + gap_severity * 0.4 + topo_boost * 0.2

        - importance_score: 越重要越优先
        - gap_severity: 越是盲区越优先
        - topo_boost: 是前置知识的优先学（前置概念先学才能理解后续）
        """
        health = self.get_graph_health()

        if self.store.node_count == 0:
            return LearningPathResult(
                graph_health=health,
                gaps=[],
                path=[],
            )

        # Step 1: 重要性
        importance = self.compute_importance()
        importance_map = {r.node_id: r for r in importance}

        # Step 2: 盲区
        gaps = self.detect_knowledge_gaps()
        gap_map = {}
        for gap in gaps:
            if gap.node_id not in gap_map or gap.severity > gap_map[gap.node_id].severity:
                gap_map[gap.node_id] = gap

        # Step 3: 拓扑排序（DAG 的依赖顺序）
        topo_order = {}
        try:
            # 知识图谱可能有环（A uses B, B uses A），用 SCC 去环
            condensed = nx.condensation(self._graph)
            topo_list = list(nx.topological_sort(condensed))
            for idx, scc_id in enumerate(topo_list):
                scc_nodes = condensed.nodes[scc_id]["members"]
                for node_id in scc_nodes:
                    topo_order[node_id] = idx
        except Exception:
            # 如果拓扑排序失败（不应该，condensation 保证无环），
            # 用度排序 fallback
            for i, node_id in enumerate(self._graph.nodes()):
                topo_order[node_id] = i

        max_topo = max(topo_order.values()) if topo_order else 1

        # Step 4: 综合排序
        candidates = []
        for node_id, node in self.store._nodes.items():
            # 过滤掉论文和作者节点（学习路径聚焦概念和方法）
            if node.node_type in (NodeType.PAPER, NodeType.AUTHOR):
                continue

            # 如果指定了聚焦领域，过滤不相关的
            if focus_area:
                focus_lower = focus_area.lower()
                label_match = focus_lower in node.label.lower()
                prop_match = any(
                    isinstance(v, str) and focus_lower in v.lower()
                    for v in node.properties.values()
                )
                # 也检查一跳邻居是否跟焦点相关
                neighbor_match = any(
                    focus_lower in (self.store.get_node(n) or KGNode(label="", node_type=NodeType.CONCEPT)).label.lower()
                    for n in list(self._graph.successors(node_id)) + list(self._graph.predecessors(node_id))
                )
                if not (label_match or prop_match or neighbor_match):
                    continue

            imp = importance_map.get(node_id)
            imp_score = imp.importance_score if imp else 0.0
            gap = gap_map.get(node_id)
            gap_score = gap.severity if gap else 0.0
            topo_idx = topo_order.get(node_id, max_topo)
            topo_boost = 1.0 - (topo_idx / max_topo) if max_topo > 0 else 0.0

            # 时间加权：越新的方法在同等条件下优先学习
            recency = imp.recency_boost if imp else 0.5
            combined = imp_score * 0.35 + gap_score * 0.35 + topo_boost * 0.15 + recency * 0.15

            # 确定优先级
            if combined > 0.6 or (gap and gap.severity > 0.7):
                priority = "critical"
            elif combined > 0.3 or (gap and gap.severity > 0.3):
                priority = "important"
            else:
                priority = "supplementary"

            # 构建前置知识列表
            prerequisites = []
            for pred in self._graph.predecessors(node_id):
                pred_node = self.store.get_node(pred)
                if pred_node and pred_node.node_type not in (NodeType.PAPER, NodeType.AUTHOR):
                    prerequisites.append(pred_node.label)

            # 构建相关论文列表
            related_papers = []
            for neighbor in list(self._graph.predecessors(node_id)) + list(self._graph.successors(node_id)):
                n_node = self.store.get_node(neighbor)
                if n_node and n_node.node_type == NodeType.PAPER:
                    related_papers.append(n_node.label)

            reason = ""
            if gap:
                reason = gap.reason
            elif imp and imp.importance_score > 0.5:
                reason = f"核心概念（重要性 {imp.importance_score:.2f}）"
            else:
                reason = "扩展知识面"

            candidates.append((
                combined,
                LearningPathItem(
                    order=0,  # 先占位，排序后再填
                    node_id=node_id,
                    label=node.label,
                    node_type=node.node_type.value,
                    priority=priority,
                    reason=reason,
                    prerequisites=prerequisites[:5],
                    related_papers=related_papers[:3],
                ),
            ))

        # 按综合分排序
        candidates.sort(key=lambda x: x[0], reverse=True)

        # 截取并设置序号
        path = []
        for i, (_, item) in enumerate(candidates[:max_items]):
            item.order = i + 1
            path.append(item)

        result = LearningPathResult(
            path=path,
            gaps=gaps,
            graph_health=health,
        )

        logger.info(
            f"学习路径生成完成: {len(path)} 个推荐, "
            f"{len(gaps)} 个盲区, 健康度={health.get('健康等级', 'N/A')}"
        )
        return result


# ================================================================
# 盲区 → 检索查询  (闭合「盲区检测 → paper-watch 自动选题」回路)
# ================================================================

@dataclass(frozen=True)
class GapQuery:
    """从一个 KnowledgeGap 派生出来的 arXiv 检索查询。

    设计意图: 让 Agent 把"我知道我不懂什么"转化为"我应该去搜什么"，
    实现"主动学习"闭环 —— 盲区检测产生检索目标，paper-watch 自动跟踪。
    """
    query: str           # 用于 arXiv 检索的关键词字符串
    gap_node_id: str     # 来源盲区的 node_id (synthetic id 也可，见 detect_knowledge_gaps)
    gap_type: str        # foundation_gap | isolated_concept | single_source | temporal_gap
    severity: float      # 来源盲区严重程度，用于排序与日志
    rationale: str       # 人类可读：为什么这个 query 能填补这个盲区


# 每个 gap_type 的查询模板。模板必须保持轻量、可被 arXiv 关键词检索吃到。
# 之所以不用 LLM 重写 query: 1) 确定性可复现 2) 单测易写 3) 离线可跑
_QUERY_TEMPLATES: dict[str, list[str]] = {
    # 基础缺失: 需要 survey/tutorial/review 这种"宏观补全"
    "foundation_gap": ["{label} survey", "{label} tutorial review"],
    # 孤立概念: 需要看它怎么和别的东西连起来 —— applications / framework 类
    "isolated_concept": ["{label} applications", "{label} framework"],
    # 单源依赖: 找跨论文的对比/改进，避免单一来源偏差
    "single_source": ["{label} comparison improvements"],
    # 时代盲区: 主动找最新进展 (硬编码"latest advances" 比写当年年份更稳健)
    "temporal_gap": ["{label} latest advances"],
}


def gaps_to_queries(
    gaps: list[KnowledgeGap],
    *,
    top_n: int = 5,
    min_severity: float = 0.0,
    max_queries_per_gap: int = 1,
) -> list[GapQuery]:
    """把盲区检测结果转成 arXiv 检索 query。

    Args:
        gaps: detect_knowledge_gaps() 的输出
        top_n: 最多保留多少个 gap 来生成 query (按 severity 排序)
        min_severity: 过滤掉严重度低于此阈值的 gap
        max_queries_per_gap: 每个 gap 最多产生几条 query (避免主题过度膨胀)

    Returns:
        GapQuery 列表，按 severity 从高到低排好序

    设计权衡:
        - 模板是确定性的硬编码：可单测，可解释，离线可跑；代价是 query 不"灵动"
        - 不调 LLM 改写 query：未来若需要，可加一层可选的 LLM enricher，
          但不能放进 critical path —— 评测希望这一步是 deterministic
        - synthetic gap node (__temporal_bias__) 用 label 作为 query 主词，
          因为 label 就是 "知识时代偏差" 这种描述性文本，配模板正好
    """
    if not gaps:
        return []
    # 过滤 + 排序
    filtered = [g for g in gaps if g.severity >= min_severity]
    filtered.sort(key=lambda g: g.severity, reverse=True)
    top = filtered[:top_n]

    out: list[GapQuery] = []
    for gap in top:
        templates = _QUERY_TEMPLATES.get(gap.gap_type, [])
        if not templates:
            # 未知 gap_type 走兜底：直接用 label
            templates = ["{label}"]
        for tmpl in templates[:max_queries_per_gap]:
            query = tmpl.format(label=gap.label).strip()
            if not query:
                continue
            out.append(GapQuery(
                query=query,
                gap_node_id=gap.node_id,
                gap_type=gap.gap_type,
                severity=gap.severity,
                rationale=f"[{gap.gap_type}] {gap.reason}",
            ))
    return out
