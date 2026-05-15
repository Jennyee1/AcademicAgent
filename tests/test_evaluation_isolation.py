from __future__ import annotations

"""Phase 0 验证：sidecar 隔离 —— env 覆盖+还原、目录树、污染检测。"""

import os
from pathlib import Path

import pytest

from src.evaluation.isolation import (
    PROTECTED_PATHS,
    ContaminationReport,
    detect_contamination,
    eval_sandbox,
    snapshot_protected,
)


def test_sandbox_creates_isolated_tree(tmp_path: Path):
    run_dir = tmp_path / "run"
    with eval_sandbox(run_dir, "task_x") as sb:
        assert sb.data_dir.exists()
        assert sb.memory_dir.exists()
        assert sb.sandbox_dir.exists()
        assert sb.root == run_dir / "sidecar" / "task_x"
        assert sb.graph_path == sb.data_dir / "knowledge_graph.json"


def test_sandbox_overrides_and_restores_env(tmp_path: Path):
    saved = os.environ.get("SCHOLARMIND_DATA_DIR")
    with eval_sandbox(tmp_path / "run", "t1") as sb:
        assert os.environ["SCHOLARMIND_DATA_DIR"] == str(sb.data_dir)
    # 退出后还原
    assert os.environ.get("SCHOLARMIND_DATA_DIR") == saved


def test_sandbox_restores_env_on_exception(tmp_path: Path):
    saved = os.environ.get("SCHOLARMIND_DATA_DIR")
    with pytest.raises(RuntimeError):
        with eval_sandbox(tmp_path / "run", "t2"):
            raise RuntimeError("boom")
    assert os.environ.get("SCHOLARMIND_DATA_DIR") == saved


def test_contamination_detection_clean():
    before = snapshot_protected()
    changed = detect_contamination(before)
    assert changed == []


def test_contamination_detection_catches_change(tmp_path: Path, monkeypatch):
    # 用一个临时文件冒充受保护文件
    fake = tmp_path / "protected.json"
    fake.write_text("original", encoding="utf-8")
    monkeypatch.setattr("src.evaluation.isolation.PROTECTED_PATHS", [fake])
    before = snapshot_protected()
    fake.write_text("MUTATED", encoding="utf-8")
    changed = detect_contamination(before)
    assert str(fake) in changed


def test_seed_graph_from_copies_fixture(tmp_path: Path):
    fixture = tmp_path / "seed.json"
    fixture.write_text('{"nodes": [], "edges": []}', encoding="utf-8")
    with eval_sandbox(tmp_path / "run", "t3") as sb:
        copied = sb.seed_graph_from(fixture)
        assert copied.exists()
        assert copied == sb.graph_path
        assert copied.read_text(encoding="utf-8") == '{"nodes": [], "edges": []}'


def test_contamination_report_to_dict():
    rep = ContaminationReport(contaminated=True, changed_paths=["/a/b"])
    d = rep.to_dict()
    assert d["contaminated"] is True
    assert d["changed_paths"] == ["/a/b"]


def test_protected_paths_point_at_real_targets():
    # 受保护路径应指向项目里真实存在的数据文件位置
    names = {p.name for p in PROTECTED_PATHS}
    assert "knowledge_graph.json" in names
    assert "MEMORY.md" in names
    assert "USER.md" in names
