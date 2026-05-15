from __future__ import annotations

"""
评测 runner —— 薄层编排器。

职责：加载并校验数据集 -> 建 RunConfig -> 快照受保护文件 ->
按层运行任务 -> 污染检测 -> 计算指标 + 聚合 -> 落盘 artifacts ->
（Phase 2）失败卡片 + 报告 ->（Phase 4）Notion 同步。

runner 本身不实现任何评测逻辑，只串联 layers / aggregate / reporting。
本地优先：data/evaluation/runs/<run_id>/ 永远是事实来源。
"""

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .aggregate import aggregate_run, compute_task_metrics
from .dataset import Dataset, DatasetError, load_dataset
from .isolation import detect_contamination, snapshot_protected
from .layers.layer1_component import run_layer1
from .layers.layer3_e2e import run_layer3
from .schema import EvalLayer, RunConfig, Tier, TaskResult
from .tracer import Tracer

logger = logging.getLogger("AcademicAgent.Eval.Runner")


def _git_hash() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _env_snapshot() -> dict[str, str]:
    """记录可复现相关的环境信息（不含密钥）。"""
    import platform
    import sys
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "minimax_model": os.getenv("MINIMAX_MODEL", "MiniMax-Text-01"),
        "has_minimax_key": str(bool(os.getenv("MINIMAX_API_KEY"))),
    }


class EvalRunner:
    """编排一次完整的评测 run。"""

    def __init__(
        self,
        dataset_path: str | Path,
        out_dir: str | Path,
        tier: Tier | None = None,
        layers: list[EvalLayer] | None = None,
        offline: bool = False,
        run_id: str | None = None,
        model: str | None = None,
        enable_e2e: bool = False,
        notion: bool = False,
        task_ids: list[str] | None = None,
    ) -> None:
        self.dataset_path = Path(dataset_path)
        self.tier = tier
        self.layers = layers or [EvalLayer.COMPONENT, EvalLayer.WORKFLOW]
        self.offline = offline
        self.enable_e2e = enable_e2e
        self.notion = notion
        self.task_ids = set(task_ids) if task_ids else None
        self.model = model or os.getenv("MINIMAX_MODEL", "MiniMax-Text-01")
        self.run_id = run_id or self._default_run_id()
        # 绝对路径：CodeSandbox 等下游对相对路径 + cwd 组合敏感，统一用绝对路径
        self.run_dir = (Path(out_dir) / self.run_id).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.tracer = Tracer(self.run_id, self.run_dir / "traces.jsonl")

    def _default_run_id(self) -> str:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
        tier_tag = self.tier.value if self.tier else "all"
        return f"{now}_{tier_tag}"

    async def run(self) -> dict[str, Any]:
        """执行评测，写出所有 artifacts，返回 run_summary。"""
        # 加载 .env，使 requires_llm/requires_api 的 skip 判断能看到密钥
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except Exception:  # noqa: BLE001
            pass
        logger.info("评测 run 开始: %s", self.run_id)
        logger.info("run 目录: %s", self.run_dir)

        # --- 1. 加载并校验数据集 ---
        dataset = load_dataset(self.dataset_path)
        problems = dataset.validate()
        if problems:
            msg = "数据集校验失败:\n  " + "\n  ".join(problems)
            logger.error(msg)
            raise DatasetError(msg)

        tasks = dataset.tasks
        if self.tier is not None:
            tasks = [t for t in tasks if t.tier == self.tier]
        tasks = [t for t in tasks if t.layer in self.layers
                 or (t.layer == EvalLayer.E2E and self.enable_e2e)]
        if self.task_ids is not None:
            tasks = [t for t in tasks if t.task_id in self.task_ids]
        logger.info("待运行任务: %d", len(tasks))

        # --- 2. RunConfig ---
        config = RunConfig(
            run_id=self.run_id,
            dataset_path=str(self.dataset_path),
            dataset_version=dataset.version.version,
            dataset_sha256=dataset.version.tasks_sha256,
            code_hash=_git_hash(),
            tiers=[self.tier.value] if self.tier else sorted({t.tier.value for t in tasks}),
            layers=[l.value for l in self.layers],
            model=self.model,
            offline=self.offline,
            env=_env_snapshot(),
        )
        self._save_json(config.to_dict(), "config.json")

        # --- 3. 污染快照（run 前）---
        protected_before = snapshot_protected()

        # --- 4. 按层运行 ---
        task_results: list[TaskResult] = []
        if EvalLayer.COMPONENT in self.layers:
            task_results += await run_layer1(
                tasks, dataset, self.run_dir, self.tracer, self.offline
            )
        if EvalLayer.WORKFLOW in self.layers:
            try:
                from .layers.layer2_workflow import run_layer2
                task_results += await run_layer2(
                    tasks, dataset, self.run_dir, self.tracer, self.offline
                )
            except ImportError:
                logger.info("Layer 2 尚未实现，跳过工作流任务")
        if self.enable_e2e:
            task_results += await run_layer3(
                tasks, dataset, self.run_dir, self.tracer, self.offline
            )

        # --- 5. 污染检测（run 后）---
        changed = detect_contamination(protected_before)
        contamination = {"contaminated": bool(changed), "changed_paths": changed}
        if changed:
            logger.error("污染检测：以下受保护文件被改动！ %s", changed)

        # --- 6. 指标计算 + 聚合 ---
        traces = self.tracer.load_events()
        task_metrics = compute_task_metrics(task_results, dataset)
        run_summary = aggregate_run(
            config, task_results, task_metrics, traces, contamination
        )

        # --- 7. 落盘核心 artifacts ---
        self._save_json([r.to_dict() for r in task_results], "task_results.json")
        self._save_json([m.to_dict() for m in task_metrics], "metrics.json")
        self._save_json(run_summary, "run_summary.json")
        self._save_json(run_summary["latency"], "latency_stats.json")
        self._save_json(run_summary["cost"], "cost.json")

        # --- 8. 门禁 ---
        from .gate import gate_from_run_dir, load_thresholds
        thresholds = load_thresholds()
        gate_result = None
        try:
            gate_result = gate_from_run_dir(self.run_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("门禁评估失败（非致命）: %s", exc)

        # --- 9. 失败卡片 ---
        self._failure_cards(
            dataset, task_results, task_metrics, traces, thresholds, contamination
        )

        # --- 10. 报告 ---
        self._reports()

        # --- 11. Notion 同步（Phase 4 起可用，本地优先、失败不阻断）---
        self._maybe_notion_sync()

        logger.info(
            "评测 run 完成: %d ok / %d failed / %d skipped%s%s",
            run_summary["totals"]["ok"],
            run_summary["totals"]["failed"],
            run_summary["totals"]["skipped"],
            "  [CONTAMINATED]" if contamination["contaminated"] else "",
            f"  [GATE {gate_result['overall']}]" if gate_result else "",
        )
        return run_summary

    # ------------------------------------------------------------------ #
    # 后处理
    # ------------------------------------------------------------------ #

    def _failure_cards(self, dataset, task_results, task_metrics, traces,
                       thresholds, contamination) -> None:
        try:
            from .failure_cards import generate_failure_cards, write_failure_artifacts
            cards = generate_failure_cards(
                dataset, task_results, task_metrics, traces,
                run_id=self.run_id, run_dir=self.run_dir,
                thresholds=thresholds, contamination=contamination,
            )
            write_failure_artifacts(cards, self.run_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("失败卡片生成失败（非致命）: %s", exc)

    def _reports(self) -> None:
        try:
            from .reporting.html import generate_html_report
            from .reporting.markdown import generate_markdown_report
            generate_html_report(self.run_dir)
            generate_markdown_report(self.run_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("报告生成失败（非致命）: %s", exc)
        try:
            from .reporting.version_log import append_version_log
            append_version_log(self.run_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("版本迭代日志追加失败（非致命）: %s", exc)

    def _maybe_notion_sync(self) -> None:
        if not self.notion:
            return
        try:
            from .notion_sync import NotionSync
            NotionSync().sync_run(self.run_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Notion 同步失败（非致命，本地结果不受影响）: %s", exc)

    def _save_json(self, data: Any, filename: str) -> None:
        path = self.run_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


async def run_evaluation(
    dataset_path: str | Path,
    out_dir: str | Path,
    tier: Tier | None = None,
    layers: list[EvalLayer] | None = None,
    offline: bool = False,
    run_id: str | None = None,
    model: str | None = None,
    enable_e2e: bool = False,
    notion: bool = False,
    task_ids: list[str] | None = None,
) -> dict[str, Any]:
    """函数式入口：构造 EvalRunner 并运行。"""
    runner = EvalRunner(
        dataset_path=dataset_path, out_dir=out_dir, tier=tier, layers=layers,
        offline=offline, run_id=run_id, model=model, enable_e2e=enable_e2e,
        notion=notion, task_ids=task_ids,
    )
    return await runner.run()
