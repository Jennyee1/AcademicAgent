from __future__ import annotations

"""
AcademicAgent Evaluation — Sidecar 隔离
========================================

评测子系统「绝不污染真实数据」的支点。

机制：
  1. eval_sandbox(run_dir, task_id) 在 run_dir/sidecar/<task_id>/ 下建立隔离目录树。
  2. 进入上下文时临时覆盖 SCHOLARMIND_DATA_DIR 指向 sidecar，退出时还原 ——
     中和 MCP server 中基于该 env 的模块级 GRAPH_PATH / SANDBOX_DIR 常量。
  3. adapters 用 SandboxPaths 直接构造隔离实例（KnowledgeGraphStore(graph_path=...)、
     CodeSandbox(work_dir=...)），不碰 MCP server 的模块级单例。
  4. 污染守卫：run 前后比对真实知识图谱与长期记忆文件的 sha256，
     变化则整个 run 标记 CONTAMINATED，让回归门禁硬失败。

为什么这是「核心」：用户的首要约束是「不污染主知识图谱和长期记忆」。
本模块用「环境变量覆盖 + 显式路径注入 + 前后哈希校验」三重保险来兑现这一点。
"""

import hashlib
import os
import shutil
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# 项目根目录（src/evaluation/isolation.py -> 上三级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 需要守卫的真实数据文件（绝对不能被评测写入）
PROTECTED_PATHS = [
    PROJECT_ROOT / "data" / "knowledge_graph.json",
    PROJECT_ROOT / "memory" / "MEMORY.md",
    PROJECT_ROOT / "memory" / "USER.md",
]


@dataclass
class SandboxPaths:
    """单个任务的隔离路径集合。"""
    task_id: str
    root: Path           # run_dir/sidecar/<task_id>/
    data_dir: Path       # SCHOLARMIND_DATA_DIR 指向这里
    graph_path: Path     # 隔离的知识图谱 JSON
    memory_dir: Path     # 隔离的 memory 目录
    sandbox_dir: Path    # 隔离的代码执行工作目录

    def seed_graph_from(self, fixture_path: str | Path) -> Path:
        """把一个 fixture seed graph 复制进隔离图谱路径，返回隔离路径。

        gap_detection / kg_query 任务用：绝不读真实图谱，只读 fixture 的拷贝。
        """
        src = Path(fixture_path)
        if not src.is_absolute():
            src = PROJECT_ROOT / src
        if not src.exists():
            raise FileNotFoundError(f"seed graph fixture 不存在: {src}")
        shutil.copy2(src, self.graph_path)
        return self.graph_path


def _sha256(path: Path) -> str:
    """文件 sha256；文件不存在返回空串。"""
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_protected() -> dict[str, str]:
    """对所有受保护文件取 sha256 快照。"""
    return {str(p): _sha256(p) for p in PROTECTED_PATHS}


def detect_contamination(before: dict[str, str]) -> list[str]:
    """对比快照，返回被改动的受保护文件列表（空列表 = 干净）。"""
    after = snapshot_protected()
    changed = []
    for path, before_hash in before.items():
        if after.get(path, "") != before_hash:
            changed.append(path)
    return changed


@contextmanager
def eval_sandbox(run_dir: Path, task_id: str) -> Iterator[SandboxPaths]:
    """为单个任务建立隔离沙箱。

    进入上下文：建目录树 + 覆盖 SCHOLARMIND_DATA_DIR。
    退出上下文：还原 SCHOLARMIND_DATA_DIR（无论成功失败）。

    注意：本上下文管理器只负责「隔离环境」，不做污染检测 ——
    污染检测由 runner 在整个 run 前后做一次（见 snapshot_protected / detect_contamination）。
    """
    run_dir = Path(run_dir)
    root = run_dir / "sidecar" / task_id
    data_dir = root / "data"
    memory_dir = root / "memory"
    sandbox_dir = root / "code_sandbox"
    for d in (data_dir, memory_dir, sandbox_dir):
        d.mkdir(parents=True, exist_ok=True)

    paths = SandboxPaths(
        task_id=task_id,
        root=root,
        data_dir=data_dir,
        graph_path=data_dir / "knowledge_graph.json",
        memory_dir=memory_dir,
        sandbox_dir=sandbox_dir,
    )

    _ENV_KEY = "SCHOLARMIND_DATA_DIR"
    saved = os.environ.get(_ENV_KEY)
    os.environ[_ENV_KEY] = str(data_dir)
    try:
        yield paths
    finally:
        if saved is None:
            os.environ.pop(_ENV_KEY, None)
        else:
            os.environ[_ENV_KEY] = saved


@dataclass
class ContaminationReport:
    """污染检测报告（写入 run_summary.json 的 totals.contaminated）。"""
    contaminated: bool = False
    changed_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "contaminated": self.contaminated,
            "changed_paths": self.changed_paths,
        }
