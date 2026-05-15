from __future__ import annotations

"""
AcademicAgent Evaluation — 数据模型
====================================

评测子系统的核心数据结构，按「层 / 能力 / 档位」组织：

- EvalLayer    : 评测分层（组件级 / 工作流级 / 端到端）
- Capability   : 被测能力（检索 / KG 抽取 / 图谱查询 / 盲区检测 / 代码执行 / 图表分析 / ...）
- Tier         : 数据集档位（smoke 门禁档 / full 完整档）
- TaskSpec     : 一条评测任务（tasks.jsonl 每行一条）
- TargetSpec   : 任务的执行目标（单工具 / 工作流 / e2e prompt）
- GoldRef      : 指向 gold 文件的引用 + 该任务要计算的指标名
- TraceEvent   : 一次工具/任务/LLM 事件的 trace 记录（JSONL）
- MetricResult : 单个指标的计算结果（带 numerator/denominator/notes，天然可解释）
- RunConfig    : 一次 run 的可复现元数据

设计原则：所有 dataclass 都提供 from_dict / to_dict，JSONL 友好；
枚举用 str-Enum，序列化即字符串。
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ============================================================
# 枚举
# ============================================================

class EvalLayer(str, Enum):
    """评测分层"""
    COMPONENT = "layer1_component"   # L1：逐 MCP 工具的组件级评测
    WORKFLOW = "layer2_workflow"     # L2：确定性脚本化多步工作流
    E2E = "layer3_e2e"               # L3：LLM 驱动端到端（本期仅接口骨架）


class Capability(str, Enum):
    """被测能力"""
    RETRIEVAL = "retrieval"            # paper_search.*
    KG_EXTRACTION = "kg_extraction"    # add_paper_to_graph / KnowledgeExtractor
    KG_QUERY = "kg_query"              # query_knowledge / get_related_concepts
    GAP_DETECTION = "gap_detection"    # detect_gaps / analyze_knowledge / importance
    CODE_EXEC = "code_exec"            # run_code / run_template
    FIGURE_ANALYSIS = "figure_analysis"  # analyze_figure / analyze_page / analyze_pdf
    WORKFLOW = "workflow"              # L2 工作流
    E2E_TASK = "e2e_task"              # L3 端到端任务


class Tier(str, Enum):
    """数据集档位"""
    SMOKE = "smoke"   # ~10 任务，可离线，<2min，回归门禁用
    FULL = "full"     # ~30-50 任务，含 API/LLM 任务


class EventType(str, Enum):
    """Trace 事件类型"""
    TASK_START = "task_start"
    TASK_END = "task_end"
    TOOL_CALL = "tool_call"
    WORKFLOW_STEP = "workflow_step"
    LLM_CALL = "llm_call"
    ERROR = "error"


class TaskStatus(str, Enum):
    """任务执行状态"""
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


# ============================================================
# 任务规格
# ============================================================

@dataclass
class TargetSpec:
    """任务的执行目标。

    - L1: tool + args（单工具调用）
    - L2: workflow（workflows/registry.py 的键）
    - L3: e2e_prompt（自由形式 prompt）
    """
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    workflow: str | None = None
    e2e_prompt: str | None = None

    @classmethod
    def from_dict(cls, d: dict | None) -> TargetSpec:
        d = dict(d or {})
        return cls(
            tool=d.get("tool"),
            args=d.get("args", {}) or {},
            workflow=d.get("workflow"),
            e2e_prompt=d.get("e2e_prompt"),
        )

    def to_dict(self) -> dict:
        out: dict[str, Any] = {}
        if self.tool is not None:
            out["tool"] = self.tool
        if self.args:
            out["args"] = self.args
        if self.workflow is not None:
            out["workflow"] = self.workflow
        if self.e2e_prompt is not None:
            out["e2e_prompt"] = self.e2e_prompt
        return out


@dataclass
class GoldRef:
    """指向 gold 文件的引用。

    gold_file : dataset 目录下的 gold JSONL 文件名（如 "kg_gold.jsonl"）
    gold_key  : 该文件中对应行的键（通常等于 task_id）
    metrics   : 该任务要计算的指标名列表（须在 METRIC_REGISTRY 中）
    """
    gold_file: str = ""
    gold_key: str = ""
    metrics: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict | None) -> GoldRef:
        d = dict(d or {})
        return cls(
            gold_file=d.get("gold_file", ""),
            gold_key=d.get("gold_key", ""),
            metrics=list(d.get("metrics", [])),
        )

    def to_dict(self) -> dict:
        return {
            "gold_file": self.gold_file,
            "gold_key": self.gold_key,
            "metrics": self.metrics,
        }


@dataclass
class TaskSpec:
    """一条评测任务（tasks.jsonl 每行一条）。"""
    task_id: str
    layer: EvalLayer
    capability: Capability
    tier: Tier
    target: TargetSpec
    gold: GoldRef = field(default_factory=GoldRef)
    timeout_s: int = 120
    requires_api: bool = False   # 需要外部 HTTP API（如 Semantic Scholar）
    requires_llm: bool = False   # 需要 LLM API key（如 MiniMax）
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> TaskSpec:
        d = dict(d)
        return cls(
            task_id=d["task_id"],
            layer=EvalLayer(d["layer"]),
            capability=Capability(d["capability"]),
            tier=Tier(d["tier"]),
            target=TargetSpec.from_dict(d.get("target")),
            gold=GoldRef.from_dict(d.get("gold")),
            timeout_s=int(d.get("timeout_s", 120)),
            requires_api=bool(d.get("requires_api", False)),
            requires_llm=bool(d.get("requires_llm", False)),
            tags=list(d.get("tags", [])),
            notes=d.get("notes", ""),
        )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "layer": self.layer.value,
            "capability": self.capability.value,
            "tier": self.tier.value,
            "target": self.target.to_dict(),
            "gold": self.gold.to_dict(),
            "timeout_s": self.timeout_s,
            "requires_api": self.requires_api,
            "requires_llm": self.requires_llm,
            "tags": self.tags,
            "notes": self.notes,
        }


# ============================================================
# Trace 事件
# ============================================================

@dataclass
class TraceEvent:
    """一次工具/任务/LLM 事件的 trace 记录。JSONL 每行一条。"""
    run_id: str
    task_id: str
    ts: str
    event_type: str
    tool_name: str = ""
    ok: bool = True
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    input_summary: str = ""
    output_summary: str = ""
    error: str = ""
    error_category: str = ""

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "ts": self.ts,
            "event_type": self.event_type,
            "tool_name": self.tool_name,
            "ok": self.ok,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "error": self.error,
            "error_category": self.error_category,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TraceEvent:
        return cls(
            run_id=d["run_id"],
            task_id=d["task_id"],
            ts=d["ts"],
            event_type=d["event_type"],
            tool_name=d.get("tool_name", ""),
            ok=d.get("ok", True),
            latency_ms=d.get("latency_ms", 0.0),
            cost_usd=d.get("cost_usd", 0.0),
            tokens_in=d.get("tokens_in", 0),
            tokens_out=d.get("tokens_out", 0),
            input_summary=d.get("input_summary", ""),
            output_summary=d.get("output_summary", ""),
            error=d.get("error", ""),
            error_category=d.get("error_category", ""),
        )


# ============================================================
# 指标结果
# ============================================================

@dataclass
class MetricResult:
    """单个指标的计算结果。

    保留 numerator/denominator/notes 三件套 —— 任何指标都能被人工复核，
    这是「可解释」的最小保证。
    """
    metric: str
    value: float
    task_id: str | None = None
    layer: str | None = None
    capability: str | None = None
    numerator: float = 0.0
    denominator: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "value": self.value,
            "task_id": self.task_id,
            "layer": self.layer,
            "capability": self.capability,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MetricResult:
        return cls(
            metric=d["metric"],
            value=d["value"],
            task_id=d.get("task_id"),
            layer=d.get("layer"),
            capability=d.get("capability"),
            numerator=d.get("numerator", 0.0),
            denominator=d.get("denominator", 0.0),
            notes=d.get("notes", ""),
        )


# ============================================================
# Run 元数据
# ============================================================

@dataclass
class RunConfig:
    """一次评测 run 的可复现元数据。"""
    run_id: str
    dataset_path: str
    dataset_version: str = "unknown"
    dataset_sha256: str = ""
    code_hash: str = ""
    tiers: list[str] = field(default_factory=list)
    layers: list[str] = field(default_factory=list)
    model: str = ""
    offline: bool = False
    env: dict[str, str] = field(default_factory=dict)
    prompt_versions: dict[str, str] = field(default_factory=dict)
    seed: int | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "dataset_path": self.dataset_path,
            "dataset_version": self.dataset_version,
            "dataset_sha256": self.dataset_sha256,
            "code_hash": self.code_hash,
            "tiers": self.tiers,
            "layers": self.layers,
            "model": self.model,
            "offline": self.offline,
            "env": self.env,
            "prompt_versions": self.prompt_versions,
            "seed": self.seed,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RunConfig:
        return cls(
            run_id=d["run_id"],
            dataset_path=d.get("dataset_path", ""),
            dataset_version=d.get("dataset_version", "unknown"),
            dataset_sha256=d.get("dataset_sha256", ""),
            code_hash=d.get("code_hash", ""),
            tiers=list(d.get("tiers", [])),
            layers=list(d.get("layers", [])),
            model=d.get("model", ""),
            offline=d.get("offline", False),
            env=d.get("env", {}),
            prompt_versions=d.get("prompt_versions", {}),
            seed=d.get("seed"),
            timestamp=d.get("timestamp", ""),
        )


# ============================================================
# 任务结果（runner 写入 task_results.json）
# ============================================================

@dataclass
class TaskResult:
    """单个任务执行后的结构化结果。"""
    task_id: str
    layer: str
    capability: str
    status: str  # ok / failed / skipped
    raw: dict[str, Any] = field(default_factory=dict)   # 结构化负载，供指标计算
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    error: str = ""
    error_category: str = ""
    skip_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "layer": self.layer,
            "capability": self.capability,
            "status": self.status,
            "raw": self.raw,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "error_category": self.error_category,
            "skip_reason": self.skip_reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TaskResult:
        return cls(
            task_id=d["task_id"],
            layer=d.get("layer", ""),
            capability=d.get("capability", ""),
            status=d.get("status", "failed"),
            raw=d.get("raw", {}),
            tokens_in=d.get("tokens_in", 0),
            tokens_out=d.get("tokens_out", 0),
            cost_usd=d.get("cost_usd", 0.0),
            latency_ms=d.get("latency_ms", 0.0),
            error=d.get("error", ""),
            error_category=d.get("error_category", ""),
            skip_reason=d.get("skip_reason", ""),
        )


# ============================================================
# 错误分类法 —— adapter error_category 与失败卡片 category 共用
# ============================================================

ERROR_CATEGORIES = (
    "llm_api_error",          # LLM API 报错（如 MiniMax 400 "description too long"）
    "rate_limit",             # 429 限流
    "timeout",                # 超时
    "network",                # 网络错误
    "parse_error",            # 输出解析失败
    "schema_violation",       # 抽取项不符合 Schema
    "empty_extraction",       # 抽取结果为空
    "metric_below_threshold", # 指标低于阈值（由 gate 产生）
    "tool_exception",         # 工具抛出未分类异常
    "isolation_contamination",# 隔离被破坏，主数据被污染
    "unknown",
)


def jsonl_dump(records: list[dict], path) -> None:
    """把 dict 列表写为 JSONL 文件。"""
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def jsonl_load(path) -> list[dict]:
    """读取 JSONL 文件为 dict 列表（文件不存在返回空列表）。"""
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
