from __future__ import annotations

"""
AcademicAgent Evaluation — 数据集加载与校验
=============================================

一个 dataset 目录的结构：

    datasets/<tier>/
        tasks.jsonl              # 每行一条 TaskSpec
        dataset_version.json     # 版本号 + 按层任务数 + tasks.jsonl 的 sha256
        retrieval_gold.jsonl     # 按 task_id 索引的 gold
        kg_gold.jsonl
        gap_gold.jsonl
        code_gold.jsonl
        figure_gold.jsonl
        workflow_gold.jsonl
        fixtures/                # seed graph、样例文本等

Dataset.validate() 对以下问题快速失败：
  - 未知工具名 / 工作流名
  - gold 行缺失
  - 未知指标名
  - 悬空 fixture 路径
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import Capability, EvalLayer, TaskSpec, Tier

# L1 已知工具名（adapters 实现的工具）
KNOWN_TOOLS = {
    # paper_search
    "search_papers", "get_paper_details", "get_related_papers", "search_arxiv",
    # knowledge_graph
    "add_paper_to_graph", "query_knowledge", "get_graph_stats", "get_related_concepts",
    # extractor（纯抽取，不过图谱去重）
    "extract_from_text",
    # learning_path
    "analyze_knowledge", "detect_gaps", "get_concept_importance",
    # code_execution
    "run_code", "run_template", "list_code_templates",
    # paper_reader
    "analyze_pdf", "analyze_figure", "analyze_page", "get_paper_structure",
}

GOLD_FILES = {
    "retrieval_gold.jsonl", "kg_gold.jsonl", "kg_query_gold.jsonl",
    "gap_gold.jsonl", "code_gold.jsonl", "figure_gold.jsonl",
    "workflow_gold.jsonl",
}


@dataclass
class DatasetVersion:
    """dataset_version.json 的内容。"""
    version: str = "0.0.0"
    created: str = ""
    task_count_by_layer: dict[str, int] = field(default_factory=dict)
    tasks_sha256: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> DatasetVersion:
        return cls(
            version=d.get("version", "0.0.0"),
            created=d.get("created", ""),
            task_count_by_layer=d.get("task_count_by_layer", {}),
            tasks_sha256=d.get("tasks_sha256", ""),
        )

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "created": self.created,
            "task_count_by_layer": self.task_count_by_layer,
            "tasks_sha256": self.tasks_sha256,
        }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DatasetError(Exception):
    """数据集校验失败。"""


@dataclass
class Dataset:
    """已加载的评测数据集。"""
    path: Path
    tasks: list[TaskSpec]
    version: DatasetVersion
    _gold_cache: dict[str, dict[str, dict]] = field(default_factory=dict)

    def gold_for(self, task: TaskSpec) -> dict | None:
        """取某任务的 gold 行（dict）；无 gold 引用时返回 None。"""
        if not task.gold.gold_file:
            return None
        table = self._load_gold_file(task.gold.gold_file)
        key = task.gold.gold_key or task.task_id
        return table.get(key)

    def _load_gold_file(self, filename: str) -> dict[str, dict]:
        if filename in self._gold_cache:
            return self._gold_cache[filename]
        table: dict[str, dict] = {}
        fpath = self.path / filename
        if fpath.exists():
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rec = json.loads(line)
                        table[rec["task_id"]] = rec
        self._gold_cache[filename] = table
        return table

    def filter(
        self,
        tier: Tier | None = None,
        layer: EvalLayer | None = None,
    ) -> list[TaskSpec]:
        """按档位 / 层过滤任务。"""
        out = self.tasks
        if tier is not None:
            out = [t for t in out if t.tier == tier]
        if layer is not None:
            out = [t for t in out if t.layer == layer]
        return out

    def validate(self) -> list[str]:
        """校验数据集，返回问题列表（空列表 = 通过）。"""
        problems: list[str] = []
        seen_ids: set[str] = set()

        # 延迟导入以避免循环依赖
        from .metrics import METRIC_REGISTRY
        try:
            from .workflows.registry import all_workflows
            WORKFLOW_REGISTRY = all_workflows()  # 触发具体工作流模块的注册
        except Exception:  # noqa: BLE001
            WORKFLOW_REGISTRY = {}

        for task in self.tasks:
            tid = task.task_id
            if tid in seen_ids:
                problems.append(f"[{tid}] 重复的 task_id")
            seen_ids.add(tid)

            # target 合法性
            if task.layer == EvalLayer.COMPONENT:
                if not task.target.tool:
                    problems.append(f"[{tid}] COMPONENT 层任务缺少 target.tool")
                elif task.target.tool not in KNOWN_TOOLS:
                    problems.append(
                        f"[{tid}] 未知工具名: {task.target.tool}"
                    )
            elif task.layer == EvalLayer.WORKFLOW:
                if not task.target.workflow:
                    problems.append(f"[{tid}] WORKFLOW 层任务缺少 target.workflow")
                elif task.target.workflow not in WORKFLOW_REGISTRY:
                    problems.append(
                        f"[{tid}] 未知工作流名: {task.target.workflow}"
                    )
            elif task.layer == EvalLayer.E2E:
                if not task.target.e2e_prompt:
                    problems.append(f"[{tid}] E2E 层任务缺少 target.e2e_prompt")

            # gold 合法性
            g = task.gold
            if g.gold_file:
                if g.gold_file not in GOLD_FILES:
                    problems.append(f"[{tid}] 未知 gold 文件: {g.gold_file}")
                else:
                    table = self._load_gold_file(g.gold_file)
                    key = g.gold_key or tid
                    if key not in table:
                        problems.append(
                            f"[{tid}] gold 行缺失: {g.gold_file} 中没有 key={key}"
                        )
                    else:
                        # 检查 fixture 路径
                        rec = table[key]
                        for fixture_key in ("seed_graph", "pdf_path", "fixture"):
                            fp = rec.get(fixture_key)
                            if fp:
                                abs_fp = self.path / fp
                                root_fp = Path(fp)
                                if not abs_fp.exists() and not root_fp.exists():
                                    problems.append(
                                        f"[{tid}] 悬空 fixture 路径: {fp}"
                                    )
                for m in g.metrics:
                    if m not in METRIC_REGISTRY:
                        problems.append(f"[{tid}] 未知指标名: {m}")

        # 版本 sha256 一致性
        tasks_file = self.path / "tasks.jsonl"
        if tasks_file.exists():
            actual = _sha256_text(tasks_file.read_text(encoding="utf-8"))
            if self.version.tasks_sha256 and self.version.tasks_sha256 != actual:
                problems.append(
                    f"dataset_version.json 的 tasks_sha256 与 tasks.jsonl 不一致 "
                    f"(记录={self.version.tasks_sha256[:12]}, 实际={actual[:12]})"
                )
        return problems


def load_dataset(path: str | Path) -> Dataset:
    """从一个 dataset 目录加载 Dataset（不做校验，调用方按需 .validate()）。"""
    path = Path(path)
    tasks_file = path / "tasks.jsonl"
    if not tasks_file.exists():
        raise DatasetError(f"tasks.jsonl 不存在: {tasks_file}")

    tasks: list[TaskSpec] = []
    with open(tasks_file, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                tasks.append(TaskSpec.from_dict(json.loads(line)))
            except Exception as exc:  # noqa: BLE001
                raise DatasetError(f"tasks.jsonl 第 {i} 行解析失败: {exc}") from exc

    version_file = path / "dataset_version.json"
    if version_file.exists():
        version = DatasetVersion.from_dict(
            json.loads(version_file.read_text(encoding="utf-8"))
        )
    else:
        version = DatasetVersion()

    return Dataset(path=path, tasks=tasks, version=version)


def compute_version(path: str | Path) -> DatasetVersion:
    """根据 tasks.jsonl 现状重新计算 DatasetVersion（用于生成/更新 dataset_version.json）。"""
    from datetime import datetime, timezone
    path = Path(path)
    tasks_file = path / "tasks.jsonl"
    text = tasks_file.read_text(encoding="utf-8")
    ds = load_dataset(path)
    by_layer: dict[str, int] = {}
    for t in ds.tasks:
        by_layer[t.layer.value] = by_layer.get(t.layer.value, 0) + 1
    return DatasetVersion(
        version=ds.version.version,
        created=ds.version.created or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        task_count_by_layer=by_layer,
        tasks_sha256=_sha256_text(text),
    )
