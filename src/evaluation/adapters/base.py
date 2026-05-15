from __future__ import annotations

"""
Adapter 基础设施 —— ToolCallResult、AdapterContext、ADAPTER_REGISTRY。

每个 adapter 是一个 async 函数：
    async def adapter(args: dict, ctx: AdapterContext) -> ToolCallResult

通过 @register_adapter("tool_name") 注册。layer runner 按工具名查表调用。
"""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class ToolCallResult:
    """一次工具调用的统一结果。

    ok             : 调用是否成功
    tool           : 工具名
    raw            : 结构化负载（供 metrics 计算，如 {"nodes": [...], "edges": [...]}）
    text           : 工具原本会返回的 Markdown 文本（供 trace 摘要与未来 LLM judge）
    error          : 错误信息文本
    error_category : schema.ERROR_CATEGORIES 之一
    tokens_in/out  : LLM token 用量（拿不到则为 0，由 cost.py 估算）
    """
    ok: bool
    tool: str
    raw: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    error: str = ""
    error_category: str = ""
    tokens_in: int = 0
    tokens_out: int = 0

    @classmethod
    def failure(
        cls,
        tool: str,
        error: str,
        error_category: str = "tool_exception",
        raw: dict | None = None,
    ) -> ToolCallResult:
        return cls(
            ok=False, tool=tool, raw=raw or {},
            error=error, error_category=error_category,
        )


@dataclass
class AdapterContext:
    """传给 adapter 的上下文。

    sandbox  : 当前任务的 SandboxPaths（隔离图谱/记忆/沙箱路径）
    gold     : 该任务的 gold 行（dict），部分 adapter 需要它取 fixture 路径
    offline  : 是否离线模式（adapter 自行决定能否在离线下工作）
    dataset_path : 数据集目录，用于解析相对 fixture 路径
    lessons  : runtime 注入的历史 FailureLesson 列表（由 failure_lookup 产出）
    hints    : critic 派生的运行时 hints；adapter 可读取 key 调整自身行为，
               未识别的 key 应被忽略。约定 key:
                 - backoff_ms      : 调用前 sleep N 毫秒
                 - retry_delay_ms  : 同上，用于 transient 错误的延迟重试
    """
    sandbox: Any
    gold: dict | None = None
    offline: bool = False
    dataset_path: Any = None
    lessons: list[Any] = field(default_factory=list)
    hints: dict[str, Any] = field(default_factory=dict)


AdapterFn = Callable[[dict, AdapterContext], Awaitable[ToolCallResult]]

ADAPTER_REGISTRY: dict[str, AdapterFn] = {}


def register_adapter(*tool_names: str) -> Callable[[AdapterFn], AdapterFn]:
    """把一个 async 函数注册为一个或多个工具名的 adapter。"""
    def deco(fn: AdapterFn) -> AdapterFn:
        for name in tool_names:
            ADAPTER_REGISTRY[name] = fn
        return fn
    return deco


def _load_all_adapters() -> None:
    """触发所有 adapter 模块的 import（从而完成注册）。

    逐模块 try/except：某个 adapter 模块缺少传递依赖（如 httpx）时，
    只让该模块的工具不可用，不拖垮其余离线 adapter。
    """
    import importlib
    import logging
    _log = logging.getLogger("AcademicAgent.Eval.Adapters")
    for mod in (
        "code_execution", "extractor", "knowledge_graph",
        "learning_path", "paper_reader", "paper_search",
    ):
        try:
            importlib.import_module(f"{__package__}.{mod}")
        except Exception as exc:  # noqa: BLE001
            _log.warning("adapter 模块 %s 加载失败（其工具将不可用）: %s", mod, exc)


def get_adapter(tool_name: str) -> AdapterFn | None:
    """按工具名取 adapter；首次调用时懒加载所有 adapter 模块。"""
    if not ADAPTER_REGISTRY:
        _load_all_adapters()
    return ADAPTER_REGISTRY.get(tool_name)
