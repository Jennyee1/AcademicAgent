from __future__ import annotations

"""
ScholarMind - 知识图谱分析与学习路径规划
===========================================

基于知识图谱的结构分析，实现三大核心能力：
  1. 图谱结构分析（PageRank, 度分布, 连通分量）
  2. 知识盲区检测（稀疏区域 + 孤立概念 + 单源依赖）
  3. 学习路径推荐（拓扑排序 + 重要性加权）

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
    importance_score: float = 0.0  # 综合重要性评分


@dataclass
class KnowledgeGap:
    """
    知识盲区

    【工程思考】盲区有三种类型：
    1. foundation_gap: 基础概念掌握不够（PageRank 高但属性稀疏）
    2. isolated_concept: 孤立概念（与其他知识缺乏连接）
    3. single_source: 单一来源依赖（一个概念只从一篇论文了解）
    """
    node_id: str
    label: str
    node_type: str
    gap_type: str          # foundation_gap | isolated_concept | single_source
    severity: float        # 严重程度 0.0 ~ 1.0
    reason: str            # 人类可读的原因描述
    suggested_action: str  # 建议的学习行动


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

        # 归一化并计算综合评分
        if results:
            max_pr = max(r.pagerank for r in results) or 1.0
            max_deg = max(r.degree for r in results) or 1
            max_in = max(r.in_degree for r in results) or 1
            max_bt = max(r.betweenness for r in results) or 1.0

            for r in results:
                r.importance_score = (
                    0.4 * (r.pagerank / max_pr)
                    + 0.3 * (r.degree / max_deg)
                    + 0.2 * (r.in_degree / max_in)
                    + 0.1 * (r.betweenness / max_bt)
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
    # 2. 知识盲区检测
    # ============================================================

    def detect_knowledge_gaps(self) -> list[KnowledgeGap]:
        """
        检测知识图谱中的盲区

        三种盲区类型：

        1. foundation_gap (基础缺失):
           - PageRank 高（是核心概念）但属性稀疏（没有详细记录定义/描述）
           - 说明你知道这个概念存在，但没有深入学习过

        2. isolated_concept (孤立概念):
           - 度 ≤ 1 且不是论文/作者类型
           - 说明这个知识点跟你其他知识没有建立联系

        3. single_source (单源依赖):
           - 一个概念只从一篇论文中了解（source_papers 只有 1 篇）
           - 说明你对这个概念的理解可能有偏见，需要交叉验证

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
            focus_area: 可选，聚焦的领域关键词（如 "beamforming"）
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

            combined = imp_score * 0.4 + gap_score * 0.4 + topo_boost * 0.2

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
