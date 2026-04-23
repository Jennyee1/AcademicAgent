from __future__ import annotations

import sys
from pathlib import Path as _Path
_PROJECT_ROOT = _Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

"""
ScholarMind - 知识图谱 MCP Server
====================================

功能：
  1. add_paper_to_graph    — 从论文文本中抽取知识并入图
  2. query_knowledge        — 自然语言查询知识图谱
  3. get_graph_stats         — 获取图谱统计摘要
  4. get_related_concepts    — 查询某概念的相关实体

技术架构：
  用户请求 → Claude Code → MCP Protocol → 本 Server
                                            ├── extractor.py (LLM 抽取)
                                            └── graph_store.py (NetworkX 存储)

工程要点：
  - 图谱持久化到 data/knowledge_graph.json
  - 每次 add_paper 后自动保存
  - 查询结果格式化为 Markdown，方便 Claude 直接展示给用户
"""

import os
import logging
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from src.knowledge.schema import NodeType, RelationType
from src.knowledge.graph_store import KnowledgeGraphStore
from src.knowledge.extractor import KnowledgeExtractor

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ScholarMind.KnowledgeGraph")

# ============================================================
# 配置
# ============================================================
# 图谱存储路径（在项目根目录的 data/ 下）
DATA_DIR = Path(os.getenv("SCHOLARMIND_DATA_DIR", str(Path(__file__).parent.parent.parent / "data")))
GRAPH_PATH = DATA_DIR / "knowledge_graph.json"

# ============================================================
# 全局实例
# ============================================================
mcp = FastMCP(
    "ScholarMind-KnowledgeGraph",
    instructions=(
        "学术知识图谱管理服务。"
        "支持从论文中自动抽取实体和关系、构建知识图谱、"
        "查询概念关联、检测知识盲区。"
        "所有数据基于真实论文内容，不编造信息。"
    ),
)

graph_store = KnowledgeGraphStore(graph_path=GRAPH_PATH)
extractor = KnowledgeExtractor()


# ============================================================
# MCP Tools
# ============================================================


@mcp.tool()
async def add_paper_to_graph(
    text: str,
    paper_title: str = "",
    paper_year: str = "",
) -> str:
    """
    从论文文本中抽取知识实体和关系，添加到知识图谱中。

    适合使用的场景：
    - 用户说"把这篇论文加入知识图谱"
    - 需要积累论文中的关键概念、方法、评估指标
    - 构建个人学术知识网络

    Args:
        text: 论文文本内容（摘要、全文或特定章节均可）
        paper_title: 论文标题（用于溯源）
        paper_year: 论文年份

    Returns:
        抽取结果摘要 + 入图统计
    """
    logger.info(f"知识抽取请求: title='{paper_title}', text_len={len(text)}")

    if len(text) < 50:
        return (
            "⚠️ **文本过短**（少于 50 字符）。\n\n"
            "请提供论文摘要或正文内容，推荐至少提供 Abstract + Method 章节。"
        )

    try:
        # Step 1: LLM 抽取
        result = await extractor.extract_from_text(
            text=text,
            paper_title=paper_title,
            paper_year=paper_year,
        )

        if not result.nodes:
            return (
                "⚠️ **未抽取到有效实体**。\n\n"
                "可能原因：\n"
                "- 文本不包含可识别的学术实体\n"
                "- 文本过短或内容不够具体\n"
                "- 建议提供论文的 Abstract + Introduction + Method 章节"
            )

        # Step 2: 写入图谱
        added_nodes = 0
        added_edges = 0

        for node in result.nodes:
            node_id = graph_store.add_node(node)
            if node_id:
                added_nodes += 1

        for edge in result.edges:
            edge_id = graph_store.add_edge(edge)
            if edge_id:
                added_edges += 1

        # Step 3: 持久化
        graph_store.save()

        # Step 4: 格式化输出
        summary = result.to_summary()
        graph_summary = (
            f"\n### 📈 图谱更新\n"
            f"- 新增/合并节点: **{added_nodes}**\n"
            f"- 新增关系: **{added_edges}**\n"
            f"- 图谱总节点: **{graph_store.node_count}**\n"
            f"- 图谱总关系: **{graph_store.edge_count}**\n\n"
            f"### 🔍 抽取的实体\n"
        )

        for node in result.nodes:
            graph_summary += (
                f"- **{node.label}** ({node.node_type.value})"
            )
            if node.properties:
                props = ", ".join(
                    f"{k}={v}"
                    for k, v in node.properties.items()
                    if isinstance(v, (str, int, float)) and v
                )
                if props:
                    graph_summary += f" — {props}"
            graph_summary += "\n"

        graph_summary += "\n### 🔗 抽取的关系\n"
        for edge in result.edges:
            source_node = graph_store.get_node(edge.source_id)
            target_node = graph_store.get_node(edge.target_id)
            source_label = source_node.label if source_node else edge.source_id
            target_label = target_node.label if target_node else edge.target_id
            graph_summary += (
                f"- {source_label} **—{edge.relation_type.value}→** "
                f"{target_label}\n"
            )

        logger.info(
            f"知识入图完成: +{added_nodes} 节点, +{added_edges} 边"
        )
        return summary + graph_summary

    except Exception as e:
        logger.exception(f"知识抽取失败: {e}")
        return f"⚠️ **知识抽取失败**: {type(e).__name__}: {e}"


@mcp.tool()
async def query_knowledge(query: str) -> str:
    """
    查询知识图谱中的信息。

    适合使用的场景：
    - 用户问"ISAC 和什么方法相关？"
    - 用户问"我读过的论文中有哪些概念？"
    - 需要查找某个方法/概念在知识图谱中的位置

    Args:
        query: 查询关键词或概念名称

    Returns:
        查询结果（匹配的节点和关系）
    """
    logger.info(f"知识查询: '{query}'")

    if graph_store.node_count == 0:
        return (
            "📭 **知识图谱为空**\n\n"
            "还没有任何论文被加入图谱。\n"
            "使用 `add_paper_to_graph` 工具添加论文内容。"
        )

    # 搜索匹配节点
    matching_nodes = graph_store.search_nodes(query)

    if not matching_nodes:
        return (
            f"🔍 未找到与 \"{query}\" 相关的实体。\n\n"
            f"当前图谱包含 {graph_store.node_count} 个节点。\n"
            f"尝试使用更具体的关键词，或使用 `get_graph_stats` 查看图谱概览。"
        )

    result = f"## 🔍 查询结果: \"{query}\"\n\n"
    result += f"找到 **{len(matching_nodes)}** 个匹配实体：\n\n"

    for node in matching_nodes[:10]:  # 最多展示10个
        result += f"### 📌 {node.label} ({node.node_type.value})\n"

        # 属性
        if node.properties:
            for key, value in node.properties.items():
                if isinstance(value, (str, int, float)) and value:
                    result += f"- **{key}**: {value}\n"

        # 关联关系
        neighbors = graph_store.query_neighbors(node.node_id, depth=1)
        if neighbors:
            result += "\n**关联实体**：\n"
            for n_node, n_edge in neighbors[:8]:
                direction = "→" if n_edge.source_id == node.node_id else "←"
                result += (
                    f"  - {direction} **{n_node.label}** "
                    f"({n_node.node_type.value}) "
                    f"[{n_edge.relation_type.value}]\n"
                )

        result += "\n---\n\n"

    return result


@mcp.tool()
async def get_graph_stats() -> str:
    """
    获取知识图谱的统计摘要。

    适合使用的场景：
    - 用户问"我的知识图谱现在是什么样的？"
    - 需要了解当前积累了多少知识
    - 查看知识图谱的整体概览

    Returns:
        图谱统计信息（节点/边数量、类型分布、核心节点等）
    """
    logger.info("获取图谱统计")

    if graph_store.node_count == 0:
        return (
            "📭 **知识图谱为空**\n\n"
            "还没有任何论文被加入图谱。\n"
            "使用 `add_paper_to_graph` 工具添加论文内容。"
        )

    return graph_store.to_markdown()


@mcp.tool()
async def get_related_concepts(
    concept_name: str,
    depth: int = 2,
) -> str:
    """
    查询某个概念的关联实体网络。

    与 query_knowledge 的区别：
    - query_knowledge: 关键词搜索，返回匹配的节点
    - get_related_concepts: 图遍历，返回多跳关联的完整子图

    适合使用的场景：
    - 用户问"和 OFDM 相关的概念有哪些？"
    - 需要探索知识图谱中某个概念的周边网络
    - 了解某个方法的上下游关系

    Args:
        concept_name: 概念名称（如 "OFDM", "Beamforming"）
        depth: 查询深度（1=直接相关, 2=两跳关联, 默认2）

    Returns:
        概念的关联网络描述
    """
    logger.info(f"关联概念查询: '{concept_name}', depth={depth}")

    # 先搜索到目标节点
    matching = graph_store.search_nodes(concept_name)

    if not matching:
        return (
            f"🔍 未找到概念 \"{concept_name}\"。\n\n"
            f"尝试使用不同的拼写或缩写。"
        )

    # 取最佳匹配
    target = matching[0]
    result = (
        f"## 🌐 关联概念网络: {target.label}\n\n"
        f"**类型**: {target.node_type.value}\n"
        f"**查询深度**: {depth} 跳\n\n"
    )

    # 多跳查询
    neighbors = graph_store.query_neighbors(target.node_id, depth=depth)

    if not neighbors:
        result += "该概念目前没有关联实体。\n"
        result += "建议添加更多论文来丰富知识图谱。\n"
        return result

    # 按类型分组展示
    by_type: dict[str, list] = {}
    for n_node, n_edge in neighbors:
        type_name = n_node.node_type.value
        if type_name not in by_type:
            by_type[type_name] = []
        by_type[type_name].append((n_node, n_edge))

    for type_name, items in by_type.items():
        result += f"### {type_name} ({len(items)})\n"
        for n_node, n_edge in items:
            direction = "→" if n_edge.source_id == target.node_id else "←"
            result += (
                f"- {direction} **{n_node.label}** "
                f"[{n_edge.relation_type.value}]"
            )
            if n_edge.confidence < 0.7:
                result += f" ⚠️低置信度({n_edge.confidence:.2f})"
            result += "\n"
        result += "\n"

    result += (
        f"---\n"
        f"📊 共找到 **{len(neighbors)}** 个关联实体 "
        f"(涵盖 {len(by_type)} 种类型)\n"
    )
    return result


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    logger.info("ScholarMind Knowledge Graph MCP Server 启动中...")
    logger.info(f"图谱路径: {GRAPH_PATH}")
    logger.info(
        f"当前图谱: {graph_store.node_count} 节点, "
        f"{graph_store.edge_count} 边"
    )
    mcp.run()
