from __future__ import annotations

"""
失败卡片 —— 把评测失败变成可执行的数据飞轮，而非一次性打分。

每个 status=failed 的任务、每个低于阈值的指标、以及污染事件，都产出一张
结构化 FailureCard：分类、严重度、精确复现命令、trace 摘要、根因假设、
修复候选、回归测试建议。根因假设来自确定性规则表（非 LLM）。

产物：
  - run_dir/failures.md                       人类可读
  - data/evaluation/failure_cards/<run_id>.jsonl   机器可读，供 cli.py promote-failures
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .dataset import Dataset
from .schema import MetricResult, TaskResult, TraceEvent

logger = logging.getLogger("AcademicAgent.Eval.FailureCards")


@dataclass
class FailureCard:
    card_id: str
    task_id: str
    layer: str
    capability: str
    category: str
    severity: str           # P0 / P1 / P2
    repro_command: str
    trace_excerpt: str
    root_cause_hypothesis: str
    fix_candidate: str
    regression_test_suggestion: str
    detail: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "task_id": self.task_id,
            "layer": self.layer,
            "capability": self.capability,
            "category": self.category,
            "severity": self.severity,
            "repro_command": self.repro_command,
            "trace_excerpt": self.trace_excerpt,
            "root_cause_hypothesis": self.root_cause_hypothesis,
            "fix_candidate": self.fix_candidate,
            "regression_test_suggestion": self.regression_test_suggestion,
            "detail": self.detail,
            "tags": self.tags,
        }


# 确定性根因规则表 —— category -> (severity, 根因假设, 修复候选, 回归测试建议)
_RULES: dict[str, tuple[str, str, str, str]] = {
    "llm_api_error": (
        "P0",
        "LLM API 报错。已知典型问题：MiniMax 对 json_schema 的 property "
        "description 有长度上限（max 200 字符），ExtractionOutput 的 schema "
        "描述超限导致 400。",
        "在 src/knowledge/extractor.py 发送前裁剪 ExtractionOutput "
        "model_json_schema() 里过长的 description 字段，或改用更短的 schema 描述。",
        "保留 smoke_kg_long 等 kg_extraction 任务在 smoke 档，确保该回归被持续监控。",
    ),
    "rate_limit": (
        "P1",
        "外部 API 触发 429 限流（Semantic Scholar 无 key 时约 1 req/s）。",
        "在 paper_search adapter 增加请求间隔/退避；或为评测配置 S2 API key；"
        "或在 smoke 档减少并发的 retrieval 任务数。",
        "retrieval 任务标记 requires_api，必要时在 CI 中跑 --offline 跳过。",
    ),
    "timeout": (
        "P1",
        "任务超过 timeout_s。可能是外部 API 慢、LLM 响应慢，或代码进入死循环。",
        "排查该工具的延迟分布（latency_stats.json）；必要时上调任务 timeout_s "
        "或优化工具实现。",
        "把该任务的 timeout_s 调到 p90 延迟的 1.5 倍并作为回归基线。",
    ),
    "network": (
        "P1",
        "网络错误（连接失败/非 429 的 HTTP 错误）。",
        "检查网络连通性与目标 API 状态；为 adapter 增加重试。",
        "在 CI 用 --offline 跑，把网络相关任务隔离到 full 档。",
    ),
    "parse_error": (
        "P1",
        "工具输出解析失败（如 LLM 返回非预期格式）。",
        "加固 adapter/底层模块的解析逻辑（fallback 提取）；固定 prompt 版本。",
        "把触发该问题的输入加入 gold 数据集作为回归样本。",
    ),
    "schema_violation": (
        "P1",
        "抽取项的 node_type/relation_type 不在合法 Schema 枚举内。",
        "检查 LLM prompt 是否完整列出了合法类型；在 extractor 解析时过滤非法类型。",
        "保留 schema_validity_rate 指标在门禁中（min 0.95）。",
    ),
    "empty_extraction": (
        "P1",
        "抽取调用成功但产出 0 节点/0 边。可能是输入信息量不足，或 prompt 失效。",
        "检查输入文本质量与 prompt；区分「合理的空」与「应有产出却空」。",
        "extraction_nonempty_rate 指标已覆盖；为正常输入设较高阈值。",
    ),
    "tool_exception": (
        "P0",
        "工具/adapter 抛出未分类异常。常见：依赖缺失、隔离图谱为空、文件不存在。",
        "查看 detail 中的异常信息定位根因；补依赖或修 adapter。",
        "为该失败场景补一个最小复现的回归任务。",
    ),
    "isolation_contamination": (
        "P0",
        "评测过程改动了受保护文件（data/knowledge_graph.json / memory/*）。"
        "这违反了「评测作为 sidecar」的核心约束。",
        "检查 adapter 是否绕过了 SCHOLARMIND_DATA_DIR 覆盖、是否用了模块级单例；"
        "确保所有写操作都指向 sandbox 路径。",
        "isolation 单测 + 每次 run 的污染守卫必须保持开启，门禁对 contaminated 硬失败。",
    ),
    "metric_below_threshold": (
        "P2",
        "指标低于 thresholds.yaml 设定的下限。可能是能力退化，也可能是阈值过严或 gold 偏差。",
        "对照 by_metric 与 baseline 判断是真退化还是噪声；必要时修能力实现或校准 gold。",
        "若确认是合理基线，更新 thresholds.yaml；否则把退化样本加入回归集。",
    ),
    "unknown": (
        "P1", "未分类失败。", "查看 detail 与 trace_excerpt 人工定位。",
        "归类后补充 _RULES 规则表。",
    ),
}


def _rule(category: str) -> tuple[str, str, str, str]:
    return _RULES.get(category, _RULES["unknown"])


def _repro_command(task_id: str, dataset_path, run_dir) -> str:
    return (
        f"python -m src.evaluation.cli run "
        f"--dataset {dataset_path} --task {task_id} "
        f"--out {Path(run_dir).parent}"
    )


def _trace_excerpt(traces: list[TraceEvent], task_id: str, limit: int = 4) -> str:
    rel = [t for t in traces if t.task_id == task_id]
    rel = rel[-limit:]
    lines = []
    for t in rel:
        lines.append(
            f"  {t.event_type}/{t.tool_name} ok={t.ok} "
            f"{t.latency_ms:.0f}ms {t.error_category} {t.error[:120]}"
        )
    return "\n".join(lines) if lines else "  (no trace events)"


def generate_failure_cards(
    dataset: Dataset,
    task_results: list[TaskResult],
    task_metrics: list[MetricResult],
    traces: list[TraceEvent],
    run_id: str,
    run_dir,
    thresholds: dict | None = None,
    contamination: dict | None = None,
) -> list[FailureCard]:
    """从失败任务、低于阈值的指标、污染事件生成失败卡片。"""
    cards: list[FailureCard] = []
    dataset_path = dataset.path
    n = 0

    # 1) 失败任务
    for tr in task_results:
        if tr.status != "failed":
            continue
        n += 1
        cat = tr.error_category or "unknown"
        severity, hypo, fix, regr = _rule(cat)
        cards.append(FailureCard(
            card_id=f"{run_id}#{n:03d}",
            task_id=tr.task_id, layer=tr.layer, capability=tr.capability,
            category=cat, severity=severity,
            repro_command=_repro_command(tr.task_id, dataset_path, run_dir),
            trace_excerpt=_trace_excerpt(traces, tr.task_id),
            root_cause_hypothesis=hypo, fix_candidate=fix,
            regression_test_suggestion=regr,
            detail=tr.error[:600],
            tags=["task_failure", cat],
        ))

    # 2) 低于阈值的指标
    thresholds = thresholds or {}
    metric_thresholds = (thresholds.get("metrics") or {})
    for m in task_metrics:
        cfg = metric_thresholds.get(m.metric)
        if not cfg:
            continue
        min_v = cfg.get("min")
        if min_v is None or m.value >= min_v:
            continue
        n += 1
        severity, hypo, fix, regr = _rule("metric_below_threshold")
        if cfg.get("warn_only"):
            severity = "P2"
        cards.append(FailureCard(
            card_id=f"{run_id}#{n:03d}",
            task_id=m.task_id or "(global)", layer=m.layer or "",
            capability=m.capability or "", category="metric_below_threshold",
            severity=severity,
            repro_command=_repro_command(m.task_id or "", dataset_path, run_dir),
            trace_excerpt=_trace_excerpt(traces, m.task_id or ""),
            root_cause_hypothesis=hypo, fix_candidate=fix,
            regression_test_suggestion=regr,
            detail=f"指标 {m.metric}={m.value:.4f} 低于阈值 {min_v} "
                   f"(numerator={m.numerator}, denominator={m.denominator}, "
                   f"notes={m.notes})",
            tags=["metric_below_threshold", m.metric],
        ))

    # 3) 污染事件
    if contamination and contamination.get("contaminated"):
        n += 1
        severity, hypo, fix, regr = _rule("isolation_contamination")
        cards.append(FailureCard(
            card_id=f"{run_id}#{n:03d}",
            task_id="(run-level)", layer="", capability="",
            category="isolation_contamination", severity=severity,
            repro_command=_repro_command("", dataset_path, run_dir),
            trace_excerpt="  (run-level contamination guard)",
            root_cause_hypothesis=hypo, fix_candidate=fix,
            regression_test_suggestion=regr,
            detail="被改动的受保护文件: " + ", ".join(contamination.get("changed_paths", [])),
            tags=["isolation_contamination"],
        ))

    return cards


def render_failures_md(cards: list[FailureCard], run_id: str) -> str:
    """把失败卡片渲染成 failures.md。"""
    if not cards:
        return f"# 失败卡片 — {run_id}\n\n本次 run 没有失败。\n"
    lines = [f"# 失败卡片 — {run_id}\n",
             f"共 {len(cards)} 张失败卡片。\n"]
    # 按 severity 排序
    order = {"P0": 0, "P1": 1, "P2": 2}
    for c in sorted(cards, key=lambda x: order.get(x.severity, 9)):
        lines += [
            f"## [{c.severity}] {c.card_id} — {c.task_id}",
            f"- **分类**: `{c.category}`",
            f"- **层/能力**: {c.layer or '-'} / {c.capability or '-'}",
            f"- **详情**: {c.detail or '-'}",
            f"- **复现**: `{c.repro_command}`",
            "- **Trace 摘要**:",
            "  ```",
            c.trace_excerpt,
            "  ```",
            f"- **根因假设**: {c.root_cause_hypothesis}",
            f"- **修复候选**: {c.fix_candidate}",
            f"- **回归测试建议**: {c.regression_test_suggestion}",
            "",
        ]
    return "\n".join(lines)


def write_failure_artifacts(cards: list[FailureCard], run_dir) -> None:
    """写 run_dir/failures.md 与 data/evaluation/failure_cards/<run_id>.jsonl。"""
    run_dir = Path(run_dir)
    run_id = run_dir.name

    (run_dir / "failures.md").write_text(
        render_failures_md(cards, run_id), encoding="utf-8"
    )

    # 机器可读 jsonl —— 放在评测根的 failure_cards/ 下，供飞轮工具消费
    cards_dir = run_dir.parent.parent / "failure_cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    with open(cards_dir / f"{run_id}.jsonl", "w", encoding="utf-8") as f:
        for c in cards:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")
    logger.info("失败卡片: %d 张 -> %s", len(cards), cards_dir / f"{run_id}.jsonl")
