# ScholarMind - Knowledge Graph Module
from .schema import (
    NodeType,
    RelationType,
    KGNode,
    KGEdge,
    ExtractionResult,
    SCHEMA_DESCRIPTION,
    SCHEMA_JSON_EXAMPLE,
)
from .graph_store import KnowledgeGraphStore
from .graph_analyzer import KnowledgeGraphAnalyzer

# KnowledgeExtractor 依赖 openai SDK (MiniMax API)，延迟导入
# 使用时通过 from src.knowledge.extractor import KnowledgeExtractor

__all__ = [
    "NodeType",
    "RelationType",
    "KGNode",
    "KGEdge",
    "ExtractionResult",
    "KnowledgeGraphStore",
    "KnowledgeGraphAnalyzer",
    "SCHEMA_DESCRIPTION",
    "SCHEMA_JSON_EXAMPLE",
]
