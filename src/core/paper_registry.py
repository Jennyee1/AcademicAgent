"""
ScholarMind - 论文注册表 (Paper Registry)
==========================================

本地论文管理模块，实现 PDF 去重、元数据记录和路径管理。

功能：
  1. check_duplicate  — 三级去重（arXiv ID → DOI → 标题模糊匹配）
  2. register_paper   — 注册新论文到本地注册表
  3. get_paper         — 按 arXiv ID / DOI / 标题查询
  4. list_papers       — 列出所有已注册论文
  5. scan_existing     — 扫描 data/papers/ 目录自动注册存量 PDF
  6. suggest_filename  — 根据元数据生成规范文件名

设计原则：
  - 零外部依赖：纯 JSON 存储，不依赖 Zotero 或数据库
  - 三级去重：arXiv ID > DOI > 标题模糊匹配（容忍大小写/标点差异）
  - 文件级去重：通过 SHA-256 哈希检测完全相同的 PDF
  - 统一存储路径：所有 PDF 归入 data/papers/ 子目录
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

logger = logging.getLogger("ScholarMind.PaperRegistry")

# 默认路径
DEFAULT_REGISTRY_PATH = Path("data/paper_registry.json")
DEFAULT_PAPERS_DIR = Path("data/papers")


# ============================================================
# 数据模型
# ============================================================
@dataclass
class PaperRecord:
    """
    单篇论文的注册记录

    Attributes:
        arxiv_id:       arXiv 标识符（如 "2210.03629"），无则 None
        doi:            DOI 标识符，无则 None
        title:          论文标题（原始大小写）
        authors:        作者列表
        year:           发表年份
        local_path:     本地 PDF 路径（相对于项目根目录）
        download_date:  下载日期（ISO 8601）
        file_hash:      PDF 文件的 SHA-256 哈希（前 16 位）
        source_url:     下载来源 URL
        tags:           用户标签（如 ["agent", "reasoning"]）
        venue:          发表会议/期刊
    """
    title: str
    local_path: str
    arxiv_id: str | None = None
    doi: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    download_date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    file_hash: str = ""
    source_url: str = ""
    tags: list[str] = field(default_factory=list)
    venue: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> PaperRecord:
        # 兼容缺失字段
        return cls(
            title=data.get("title", "Unknown"),
            local_path=data.get("local_path", ""),
            arxiv_id=data.get("arxiv_id"),
            doi=data.get("doi"),
            authors=data.get("authors", []),
            year=data.get("year"),
            download_date=data.get("download_date", ""),
            file_hash=data.get("file_hash", ""),
            source_url=data.get("source_url", ""),
            tags=data.get("tags", []),
            venue=data.get("venue", ""),
        )


# ============================================================
# 工具函数
# ============================================================
def _normalize_title(title: str) -> str:
    """
    标题标准化：小写 + 去除标点 + 压缩空格

    用于模糊匹配，容忍大小写和标点差异。
    例如：
      "ReAct: Synergizing Reasoning and Acting in Language Models"
      → "react synergizing reasoning and acting in language models"
    """
    t = title.lower().strip()
    t = re.sub(r"[^a-z0-9\s]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _compute_file_hash(filepath: Path, length: int = 16) -> str:
    """计算文件 SHA-256 哈希（前 length 位）"""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()[:length]


def _extract_arxiv_id_from_filename(filename: str) -> str | None:
    """
    从文件名中尝试提取 arXiv ID

    支持格式：
      - "2210.03629.pdf"
      - "arxiv_2210_03629.pdf"
      - "ReAct_2210.03629.pdf"
      - "2210.03629v3.pdf"
    """
    # 匹配 YYMM.NNNNN 格式（可能带版本号 vN）
    match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", filename)
    if match:
        return match.group(1)
    # 匹配下划线分隔格式 arxiv_2210_03629
    match = re.search(r"arxiv[_\-]?(\d{4})[_\-](\d{4,5})", filename, re.IGNORECASE)
    if match:
        return f"{match.group(1)}.{match.group(2)}"
    return None


def suggest_filename(
    title: str,
    arxiv_id: str | None = None,
    year: int | None = None,
) -> str:
    """
    根据论文元数据生成规范化文件名

    格式：{简化标题}_{arXiv ID 或 年份}.pdf
    例如：ReAct_2210.03629.pdf
    """
    # 取标题的前几个关键词
    words = re.sub(r"[^a-zA-Z0-9\s]", "", title).split()
    # 取前 3 个有意义的词（跳过冠词等）
    skip = {"a", "an", "the", "of", "in", "on", "for", "and", "with", "to", "is"}
    key_words = [w for w in words if w.lower() not in skip][:3]
    name_part = "_".join(key_words) if key_words else "paper"

    # 标识符部分
    if arxiv_id:
        id_part = arxiv_id.replace("/", "_")
    elif year:
        id_part = str(year)
    else:
        id_part = datetime.now().strftime("%Y%m%d")

    return f"{name_part}_{id_part}.pdf"


# ============================================================
# Paper Registry 主类
# ============================================================
class PaperRegistry:
    """
    本地论文注册表

    Usage:
        registry = PaperRegistry()
        
        # 检查是否重复
        dup = registry.check_duplicate(arxiv_id="2210.03629")
        if dup:
            print(f"已存在: {dup.title} @ {dup.local_path}")
        else:
            # 下载并注册
            record = PaperRecord(
                title="ReAct: ...",
                arxiv_id="2210.03629",
                local_path="data/papers/ReAct_2210.03629.pdf",
            )
            registry.register_paper(record)
    """

    def __init__(
        self,
        registry_path: str | Path = DEFAULT_REGISTRY_PATH,
        papers_dir: str | Path = DEFAULT_PAPERS_DIR,
    ):
        self._registry_path = Path(registry_path)
        self._papers_dir = Path(papers_dir)
        self._papers: list[PaperRecord] = []

        # 确保目录存在
        self._papers_dir.mkdir(parents=True, exist_ok=True)
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)

        # 加载已有注册表
        if self._registry_path.exists():
            self._load()
            logger.info(f"加载论文注册表: {len(self._papers)} 篇")

    # ============================================================
    # 去重检查（核心）
    # ============================================================
    def check_duplicate(
        self,
        arxiv_id: str | None = None,
        doi: str | None = None,
        title: str | None = None,
        file_hash: str | None = None,
    ) -> PaperRecord | None:
        """
        三级去重检查，返回匹配的已有记录（如果存在）

        优先级：arXiv ID > DOI > 文件哈希 > 标题模糊匹配
        """
        # Level 1: arXiv ID 精确匹配
        if arxiv_id:
            clean_id = arxiv_id.split("v")[0]  # 去掉版本号 "2210.03629v3" → "2210.03629"
            for p in self._papers:
                if p.arxiv_id and p.arxiv_id.split("v")[0] == clean_id:
                    logger.info(f"去重命中 [arXiv ID]: {clean_id} → {p.title}")
                    return p

        # Level 2: DOI 精确匹配
        if doi:
            doi_lower = doi.lower().strip()
            for p in self._papers:
                if p.doi and p.doi.lower().strip() == doi_lower:
                    logger.info(f"去重命中 [DOI]: {doi} → {p.title}")
                    return p

        # Level 3: 文件哈希匹配
        if file_hash:
            for p in self._papers:
                if p.file_hash and p.file_hash == file_hash:
                    logger.info(f"去重命中 [文件哈希]: {file_hash} → {p.title}")
                    return p

        # Level 4: 标题模糊匹配
        if title:
            norm_query = _normalize_title(title)
            if len(norm_query) < 5:
                return None  # 标题太短，不做模糊匹配
            for p in self._papers:
                norm_existing = _normalize_title(p.title)
                # 完全匹配或包含关系
                if norm_query == norm_existing:
                    logger.info(f"去重命中 [标题精确]: {title} → {p.title}")
                    return p
                # 子串包含（一个标题包含另一个的 80% 以上）
                # 注意：长度相同时 min/max 会让 shorter==longer，导致 `in` 永真
                if (
                    len(norm_query) > 10
                    and len(norm_existing) > 10
                    and len(norm_query) != len(norm_existing)
                ):
                    shorter = min(norm_query, norm_existing, key=len)
                    longer = max(norm_query, norm_existing, key=len)
                    if shorter in longer and len(shorter) / len(longer) > 0.7:
                        logger.info(f"去重命中 [标题模糊]: {title} → {p.title}")
                        return p

        return None

    # ============================================================
    # 注册 & 管理
    # ============================================================
    def register_paper(self, record: PaperRecord) -> PaperRecord:
        """
        注册新论文

        如果检测到重复，返回已有记录而不是重复注册。
        注册后自动保存到 JSON。
        """
        # 再次检查去重（防止调用方忘记 check_duplicate）
        existing = self.check_duplicate(
            arxiv_id=record.arxiv_id,
            doi=record.doi,
            title=record.title,
            file_hash=record.file_hash,
        )
        if existing:
            logger.warning(f"论文已存在，跳过注册: {record.title}")
            return existing

        # 补充文件哈希
        if not record.file_hash and record.local_path:
            filepath = Path(record.local_path)
            if filepath.exists():
                record.file_hash = _compute_file_hash(filepath)

        self._papers.append(record)
        self._save()
        logger.info(
            f"论文注册成功: {record.title} "
            f"[arXiv: {record.arxiv_id or 'N/A'}] "
            f"→ {record.local_path}"
        )
        return record

    def get_paper(
        self,
        arxiv_id: str | None = None,
        doi: str | None = None,
        title: str | None = None,
    ) -> PaperRecord | None:
        """按标识符查询论文"""
        return self.check_duplicate(arxiv_id=arxiv_id, doi=doi, title=title)

    def list_papers(self) -> list[PaperRecord]:
        """列出所有已注册论文"""
        return list(self._papers)

    @property
    def count(self) -> int:
        return len(self._papers)

    # ============================================================
    # 存量 PDF 扫描
    # ============================================================
    def scan_existing(self, scan_dir: str | Path | None = None) -> list[PaperRecord]:
        """
        扫描目录中已有的 PDF 文件，尝试自动注册

        对每个 PDF：
        1. 计算文件哈希，检查是否已注册
        2. 从文件名提取 arXiv ID（如果可能）
        3. 创建记录并注册

        Args:
            scan_dir: 要扫描的目录，默认 data/papers/

        Returns:
            新注册的论文列表
        """
        target_dir = Path(scan_dir) if scan_dir else self._papers_dir
        if not target_dir.exists():
            logger.warning(f"扫描目录不存在: {target_dir}")
            return []

        new_records = []
        pdf_files = list(target_dir.glob("*.pdf"))
        logger.info(f"扫描目录 {target_dir}: 发现 {len(pdf_files)} 个 PDF")

        for pdf_path in pdf_files:
            file_hash = _compute_file_hash(pdf_path)

            # 检查是否已注册
            existing = self.check_duplicate(file_hash=file_hash)
            if existing:
                logger.debug(f"跳过已注册: {pdf_path.name}")
                continue

            # 从文件名提取信息
            arxiv_id = _extract_arxiv_id_from_filename(pdf_path.name)
            # 文件名去掉扩展名和 arXiv ID 作为标题猜测
            title_guess = pdf_path.stem
            # 清理常见的 ID 模式
            title_guess = re.sub(r"_?\d{4}\.\d{4,5}(v\d+)?", "", title_guess)
            title_guess = re.sub(r"_?arxiv[_\-]?\d{4}[_\-]\d{4,5}", "", title_guess, flags=re.IGNORECASE)
            title_guess = title_guess.strip("_- ").replace("_", " ")
            if not title_guess:
                title_guess = pdf_path.stem

            record = PaperRecord(
                title=title_guess,
                arxiv_id=arxiv_id,
                local_path=str(pdf_path.as_posix()),
                file_hash=file_hash,
                download_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                tags=["auto-scanned"],
            )

            # 再次去重（用 arXiv ID 和标题检查）
            dup = self.check_duplicate(
                arxiv_id=arxiv_id, title=title_guess, file_hash=file_hash
            )
            if dup:
                continue

            self._papers.append(record)
            new_records.append(record)
            logger.info(f"自动注册: {pdf_path.name} (arXiv: {arxiv_id or 'N/A'})")

        if new_records:
            self._save()
            logger.info(f"扫描完成: 新注册 {len(new_records)} 篇论文")

        return new_records

    # ============================================================
    # PDF 迁移工具
    # ============================================================
    def migrate_pdfs(
        self,
        source_dir: str | Path,
        dry_run: bool = False,
    ) -> list[dict]:
        """
        将散落的 PDF 迁移到 data/papers/ 并自动注册

        Args:
            source_dir: 源目录（如 data/）
            dry_run: 如果 True，只预览不执行

        Returns:
            迁移结果列表 [{source, dest, action, arxiv_id}]
        """
        source = Path(source_dir)
        results = []

        pdf_files = [f for f in source.glob("*.pdf") if f.is_file()]
        logger.info(f"迁移扫描: {source} → {self._papers_dir}, 发现 {len(pdf_files)} 个 PDF")

        # 按文件哈希分组，检测重复文件
        hash_groups: dict[str, list[Path]] = {}
        for pdf in pdf_files:
            h = _compute_file_hash(pdf)
            hash_groups.setdefault(h, []).append(pdf)

        for file_hash, files in hash_groups.items():
            # 选择最优文件名（优先包含 arXiv ID 的）
            best_file = files[0]
            for f in files:
                if _extract_arxiv_id_from_filename(f.name):
                    best_file = f
                    break

            arxiv_id = _extract_arxiv_id_from_filename(best_file.name)
            dest_name = best_file.name
            dest_path = self._papers_dir / dest_name

            # 如果目标已存在同名文件，跳过
            if dest_path.exists():
                existing_hash = _compute_file_hash(dest_path)
                if existing_hash == file_hash:
                    action = "skip_exists"
                else:
                    # 同名不同内容，加后缀
                    stem = dest_path.stem
                    dest_path = self._papers_dir / f"{stem}_{file_hash[:6]}.pdf"
                    action = "move_renamed"
            else:
                action = "move"

            result = {
                "source": [str(f) for f in files],
                "dest": str(dest_path),
                "action": action,
                "arxiv_id": arxiv_id,
                "duplicates": len(files) - 1,
            }
            results.append(result)

            if not dry_run and action in ("move", "move_renamed"):
                shutil.copy2(best_file, dest_path)
                logger.info(f"迁移: {best_file.name} → {dest_path}")
                # 清理重复文件
                for f in files:
                    if f != best_file and f.exists():
                        f.unlink()
                        logger.info(f"清理重复: {f.name}")
                # 如果源文件不在目标目录，也删除
                if best_file.parent != self._papers_dir and best_file.exists():
                    best_file.unlink()

        return results

    # ============================================================
    # 格式化输出
    # ============================================================
    def format_duplicate_warning(self, record: PaperRecord) -> str:
        """生成去重警告信息（供 Workflow 使用）"""
        lines = [
            "⚠️ **论文已存在，无需重复下载！**",
            "",
            f"| 属性 | 值 |",
            f"|:---|:---|",
            f"| **标题** | {record.title} |",
        ]
        if record.arxiv_id:
            lines.append(f"| **arXiv ID** | `{record.arxiv_id}` |")
        if record.doi:
            lines.append(f"| **DOI** | `{record.doi}` |")
        lines.extend([
            f"| **本地路径** | `{record.local_path}` |",
            f"| **下载日期** | {record.download_date} |",
        ])
        if record.venue:
            lines.append(f"| **发表于** | {record.venue} |")
        lines.append("")
        lines.append("→ 直接使用已有文件即可，跳过下载步骤。")
        return "\n".join(lines)

    def format_registry_summary(self) -> str:
        """生成注册表摘要（Markdown 格式）"""
        if not self._papers:
            return "📚 **论文注册表为空**\n\n还没有注册任何论文。"

        lines = [
            f"## 📚 本地论文库（共 {len(self._papers)} 篇）",
            "",
            "| # | 标题 | arXiv ID | 年份 | 本地路径 |",
            "|:---|:---|:---|:---|:---|",
        ]
        for i, p in enumerate(self._papers, 1):
            title_short = p.title[:50] + ("..." if len(p.title) > 50 else "")
            arxiv = f"`{p.arxiv_id}`" if p.arxiv_id else "—"
            year = str(p.year) if p.year else "—"
            lines.append(f"| {i} | {title_short} | {arxiv} | {year} | `{p.local_path}` |")

        return "\n".join(lines)

    # ============================================================
    # 持久化
    # ============================================================
    def _save(self):
        """保存注册表到 JSON"""
        data = {
            "metadata": {
                "count": len(self._papers),
                "last_updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "version": "1.0",
            },
            "papers": [p.to_dict() for p in self._papers],
        }
        with open(self._registry_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug(f"注册表已保存: {self._registry_path} ({len(self._papers)} 篇)")

    def _load(self):
        """从 JSON 加载注册表"""
        with open(self._registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._papers = [
            PaperRecord.from_dict(p) for p in data.get("papers", [])
        ]


# ============================================================
# CLI 入口（独立运行时使用）
# ============================================================
def main():
    """命令行工具：扫描、迁移、查询论文"""
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="ScholarMind Paper Registry")
    sub = parser.add_subparsers(dest="command")

    # scan — 扫描已有 PDF
    scan_p = sub.add_parser("scan", help="扫描目录中的 PDF 并自动注册")
    scan_p.add_argument("--dir", default="data/papers", help="扫描目录")

    # migrate — 迁移 PDF
    migrate_p = sub.add_parser("migrate", help="将 data/ 下的 PDF 迁移到 data/papers/")
    migrate_p.add_argument("--source", default="data", help="源目录")
    migrate_p.add_argument("--dry-run", action="store_true", help="预览模式")

    # list — 列出所有论文
    sub.add_parser("list", help="列出所有已注册论文")

    # check — 查重
    check_p = sub.add_parser("check", help="检查论文是否已存在")
    check_p.add_argument("--arxiv", help="arXiv ID")
    check_p.add_argument("--title", help="论文标题")
    check_p.add_argument("--doi", help="DOI")

    args = parser.parse_args()
    registry = PaperRegistry()

    if args.command == "scan":
        new = registry.scan_existing(args.dir)
        print(f"\n新注册 {len(new)} 篇论文")
        for r in new:
            print(f"  - {r.title} (arXiv: {r.arxiv_id or 'N/A'})")

    elif args.command == "migrate":
        results = registry.migrate_pdfs(args.source, dry_run=args.dry_run)
        print(f"\n迁移结果 ({'预览' if args.dry_run else '执行'}):")
        for r in results:
            print(f"  [{r['action']}] {r['source']} → {r['dest']}")
            if r["duplicates"] > 0:
                print(f"          (发现 {r['duplicates']} 个重复文件)")

    elif args.command == "list":
        print(registry.format_registry_summary())

    elif args.command == "check":
        dup = registry.check_duplicate(
            arxiv_id=args.arxiv, doi=args.doi, title=args.title
        )
        if dup:
            print(registry.format_duplicate_warning(dup))
        else:
            print("✅ 未找到重复，可以下载。")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
