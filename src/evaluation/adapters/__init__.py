from __future__ import annotations

"""
Adapters —— 对 Agent 真实组件的类型化封装。

这是评测子系统中**唯一**允许 import src/mcp_servers、src/knowledge、
src/execution、src/core 的地方。每个 adapter 方法返回统一的 ToolCallResult，
既给 tracer 提供文本摘要，也给 metrics 提供结构化负载。
"""

from .base import ADAPTER_REGISTRY, ToolCallResult, get_adapter  # noqa: F401
