#!/usr/bin/env python3
"""
ScholarMind Paper Watch — 盲区驱动模式
==========================================

闭合 "PageRank 盲区检测 → paper-watch 自动选题" 回路：
  1. 从持久化知识图谱加载结构
  2. detect_knowledge_gaps() 得到当前盲区
  3. gaps_to_queries() 把盲区翻译成 arXiv 检索 query
  4. fetch_arxiv() 拉对应近期论文
  5. 输出带"盲区归因"的 digest —— 每篇论文都能说明它在补哪个盲区

与 fetch_papers.py 的区别:
  - fetch_papers.py 从 USER.md 读静态主题
  - 本脚本从知识图谱当前状态动态生成主题，是 "self-improving" 闭环的一步

用法:
    # 默认: 用持久化图谱产生 5 个最严重盲区的 query，搜最近 7 天
    python gap_driven_watch.py

    # 限制 top-N 和最低 severity
    python gap_driven_watch.py --top-n 3 --min-severity 0.4

    # 不实际抓 arXiv，只打印将要使用的 query (dry-run)
    python gap_driven_watch.py --dry-run

输出:
    data/paper_watch/gap_driven_YYYY-MM-DD.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 复用既有 paper_watch 的 arXiv 客户端，不重复造轮子
from skills.paper_watch.scripts.fetch_papers import fetch_arxiv, REQUEST_INTERVAL
from src.knowledge.graph_analyzer import (
    GapQuery,
    KnowledgeGraphAnalyzer,
    gaps_to_queries,
)
from src.knowledge.graph_store import KnowledgeGraphStore

DATA_DIR = Path(os.getenv("SCHOLARMIND_DATA_DIR", str(PROJECT_ROOT / "data")))
WATCH_DIR = DATA_DIR / "paper_watch"
GRAPH_PATH = DATA_DIR / "knowledge_graph.json"


def collect_gap_driven_papers(
    *,
    graph_path: Path,
    top_n: int = 5,
    min_severity: float = 0.0,
    max_results_per_query: int = 3,
    days: int = 7,
    arxiv_fetcher=fetch_arxiv,
    request_interval: float = REQUEST_INTERVAL,
) -> dict:
    """加载图谱 -> 盲区 -> query -> arXiv 论文 -> 带归因的 digest。

    arxiv_fetcher 默认是真实 fetch_arxiv，测试时注入 mock 即可完全离线。
    """
    # KnowledgeGraphStore 在 __init__ 内会自动 load(graph_path)
    store = KnowledgeGraphStore(graph_path=graph_path)
    analyzer = KnowledgeGraphAnalyzer(store)
    gaps = analyzer.detect_knowledge_gaps()

    queries = gaps_to_queries(
        gaps, top_n=top_n, min_severity=min_severity,
    )

    papers_by_id: dict[str, dict] = {}
    query_records: list[dict] = []
    for gq in queries:
        try:
            papers = arxiv_fetcher(
                gq.query, max_results=max_results_per_query, days=days,
            )
        except Exception as exc:  # noqa: BLE001 — 一个 query 失败不应炸整个 digest
            papers = []
            query_records.append({
                "query": gq.query, "gap_node_id": gq.gap_node_id,
                "gap_type": gq.gap_type, "severity": gq.severity,
                "rationale": gq.rationale, "matched_count": 0,
                "error": str(exc),
            })
            time.sleep(request_interval)
            continue

        matched_ids = []
        for paper in papers:
            arxiv_id = paper.get("arxiv_id")
            if not arxiv_id:
                continue
            # 把"补哪个盲区"贴在每篇论文上，多盲区命中同一篇时合并
            existing = papers_by_id.get(arxiv_id)
            attribution = {
                "gap_node_id": gq.gap_node_id,
                "gap_type": gq.gap_type,
                "severity": gq.severity,
                "query": gq.query,
            }
            if existing is None:
                paper_with_attr = dict(paper)
                paper_with_attr["gap_attributions"] = [attribution]
                papers_by_id[arxiv_id] = paper_with_attr
            else:
                existing.setdefault("gap_attributions", []).append(attribution)
            matched_ids.append(arxiv_id)

        query_records.append({
            "query": gq.query, "gap_node_id": gq.gap_node_id,
            "gap_type": gq.gap_type, "severity": gq.severity,
            "rationale": gq.rationale,
            "matched_count": len(matched_ids),
            "matched_arxiv_ids": matched_ids,
        })
        time.sleep(request_interval)

    return {
        "mode": "gap_driven",
        "fetch_date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "time_window_days": days,
        "graph_snapshot": {
            "path": str(graph_path),
            "node_count": len(store._nodes) if hasattr(store, "_nodes") else 0,
            "gap_count_detected": len(gaps),
        },
        "queries": query_records,
        "papers": list(papers_by_id.values()),
        "total_count": len(papers_by_id),
    }


def save_digest(digest: dict) -> Path:
    """落盘到 data/paper_watch/gap_driven_YYYY-MM-DD.json。"""
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = WATCH_DIR / f"gap_driven_{date}.json"
    path.write_text(
        json.dumps(digest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def print_summary(digest: dict) -> None:
    """命令行可读的简报。"""
    print(f"\n📊 知识图谱: {digest['graph_snapshot']['node_count']} 节点, "
          f"{digest['graph_snapshot']['gap_count_detected']} 盲区")
    print(f"🎯 触发 {len(digest['queries'])} 条盲区驱动 query")
    print(f"📚 命中 {digest['total_count']} 篇论文 (最近 {digest['time_window_days']} 天)\n")
    for q in digest["queries"]:
        line = (
            f"  [{q['gap_type']:<18s} sev={q['severity']:.2f}] "
            f"{q['query']:<40s} -> {q['matched_count']} 篇"
        )
        if "error" in q:
            line += f"  ⚠️ {q['error']}"
        print(line)
    if digest["papers"]:
        print(f"\n📰 前 5 篇 (按盲区严重度排序):")
        sorted_papers = sorted(
            digest["papers"],
            key=lambda p: max(
                (a["severity"] for a in p.get("gap_attributions", [])),
                default=0.0,
            ),
            reverse=True,
        )
        for i, p in enumerate(sorted_papers[:5], 1):
            attrs = p.get("gap_attributions", [])
            tag = ", ".join(sorted({a["gap_type"] for a in attrs}))
            print(f"   {i}. [{p['published']}] [{tag}] {p['title'][:60]}")


def main():
    parser = argparse.ArgumentParser(
        description="盲区驱动的 paper-watch (闭合盲区检测 → 自动选题回路)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--graph", default=str(GRAPH_PATH),
                        help=f"知识图谱 JSON 路径 (默认 {GRAPH_PATH})")
    parser.add_argument("--top-n", type=int, default=5,
                        help="最多用前 N 个最严重的盲区生成 query (默认 5)")
    parser.add_argument("--min-severity", type=float, default=0.0,
                        help="过滤掉 severity 低于此阈值的盲区 (默认 0.0)")
    parser.add_argument("--max-results-per-query", type=int, default=3,
                        help="每条 query 最多返回多少篇论文 (默认 3)")
    parser.add_argument("--days", type=int, default=7,
                        help="只看最近 N 天 (默认 7)")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印将要使用的 query，不实际访问 arXiv")
    args = parser.parse_args()

    graph_path = Path(args.graph)
    if not graph_path.exists():
        print(f"❌ 知识图谱不存在: {graph_path}")
        print("   先用 /paper-analysis 或 /knowledge-build 把至少一篇论文加进图谱")
        sys.exit(1)

    if args.dry_run:
        store = KnowledgeGraphStore(graph_path=graph_path)
        analyzer = KnowledgeGraphAnalyzer(store)
        gaps = analyzer.detect_knowledge_gaps()
        queries = gaps_to_queries(
            gaps, top_n=args.top_n, min_severity=args.min_severity,
        )
        print(f"📊 知识图谱: {len(store._nodes)} 节点, {len(gaps)} 盲区")
        print(f"🎯 将要使用 {len(queries)} 条 query (dry-run, 不访问 arXiv):\n")
        for q in queries:
            print(f"  [{q.gap_type:<18s} sev={q.severity:.2f}] {q.query}")
            print(f"     {q.rationale}")
        return

    print(f"⏳ 加载图谱并检测盲区...")
    digest = collect_gap_driven_papers(
        graph_path=graph_path,
        top_n=args.top_n,
        min_severity=args.min_severity,
        max_results_per_query=args.max_results_per_query,
        days=args.days,
    )
    output_path = save_digest(digest)
    print_summary(digest)
    print(f"\n✅ 完成. 保存到: {output_path}")


if __name__ == "__main__":
    main()
