#!/usr/bin/env python3
"""
ScholarMind Paper Watch — 论文追踪脚本
==========================================

定时抓取 arXiv 近期论文，独立运行不依赖宿主/LLM。

用法:
    # 从 USER.md 读关键词，抓最近 7 天
    python fetch_papers.py

    # 手动指定关键词
    python fetch_papers.py --topics "ISAC,RIS,channel estimation"

    # 指定时间范围
    python fetch_papers.py --days 3

    # 查看今日已有摘要
    python fetch_papers.py --action summary

输出:
    data/paper_watch/YYYY-MM-DD.json

【工程思考】为什么选 arXiv 而不是 Semantic Scholar？
  - arXiv API 原生支持 submittedDate 范围筛选
  - arXiv 是预印本平台，论文更新最快
  - 无需 API Key，限速宽松 (3 req/s)
  - Semantic Scholar 更适合做引用网络分析（深度），不适合做新鲜度追踪（广度）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Windows 下强制 UTF-8 输出（避免 GBK 编码 emoji 报错）
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import os

DATA_DIR = Path(os.getenv("SCHOLARMIND_DATA_DIR", str(PROJECT_ROOT / "data")))
WATCH_DIR = DATA_DIR / "paper_watch"
USER_MD_PATH = PROJECT_ROOT / "memory" / "USER.md"

# arXiv API
ARXIV_API_BASE = "https://export.arxiv.org/api/query"
REQUEST_INTERVAL = 0.5  # arXiv 建议不超过 3 req/s


def load_topics_from_user_md() -> list[str]:
    """从 memory/USER.md 解析研究方向关键词"""
    if not USER_MD_PATH.exists():
        print("⚠️ memory/USER.md 不存在，请使用 --topics 手动指定关键词")
        return []

    text = USER_MD_PATH.read_text(encoding="utf-8")

    # 尝试匹配"研究方向"或"Research"章节下的列表项
    topics = []
    in_section = False
    for line in text.split("\n"):
        if re.search(r"(研究方向|research|interests)", line, re.IGNORECASE):
            in_section = True
            continue
        if in_section:
            if line.startswith("#"):
                break  # 遇到下一个标题，停止
            match = re.match(r"\s*[-*]\s*(.+)", line)
            if match:
                topic = match.group(1).strip()
                if topic:
                    topics.append(topic)

    return topics


def fetch_arxiv(query: str, max_results: int = 5, days: int = 7) -> list[dict]:
    """
    调用 arXiv API 搜索近期论文

    Args:
        query: 搜索关键词
        max_results: 最大返回数
        days: 最近 N 天

    Returns:
        论文列表
    """
    # arXiv API 查询参数
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    url = f"{ARXIV_API_BASE}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ScholarMind/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            xml_data = response.read().decode("utf-8")
    except Exception as e:
        print(f"  ⚠️ arXiv API 请求失败: {e}")
        return []

    # 解析 XML
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(xml_data)

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    papers = []

    for entry in root.findall("atom:entry", ns):
        # 解析发布日期
        published_str = entry.findtext("atom:published", "", ns)
        try:
            published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        # 过滤超出时间范围的论文
        if published < cutoff_date:
            continue

        # 提取 arXiv ID
        entry_id = entry.findtext("atom:id", "", ns)
        arxiv_id = entry_id.split("/abs/")[-1] if "/abs/" in entry_id else entry_id

        # 提取作者
        authors = [
            a.findtext("atom:name", "", ns)
            for a in entry.findall("atom:author", ns)
        ]

        # 提取 PDF 链接
        pdf_url = ""
        for link in entry.findall("atom:link", ns):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
                break

        # 提取分类
        categories = [
            c.get("term", "")
            for c in entry.findall("atom:category", ns)
        ]

        papers.append({
            "title": entry.findtext("atom:title", "", ns).strip().replace("\n", " "),
            "authors": authors[:5],  # 只保留前 5 个作者
            "abstract": entry.findtext("atom:summary", "", ns).strip().replace("\n", " "),
            "arxiv_id": arxiv_id,
            "published": published_str[:10],
            "pdf_url": pdf_url or f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            "categories": categories[:3],
        })

    return papers


def fetch_all(topics: list[str], max_results: int = 5, days: int = 7) -> dict:
    """对多个主题依次搜索，汇总去重"""
    all_papers = {}
    seen_ids = set()

    for topic in topics:
        print(f"  🔍 搜索: {topic}")
        papers = fetch_arxiv(topic, max_results=max_results, days=days)
        for paper in papers:
            if paper["arxiv_id"] not in seen_ids:
                seen_ids.add(paper["arxiv_id"])
                all_papers[paper["arxiv_id"]] = paper
        time.sleep(REQUEST_INTERVAL)  # 限速

    result = {
        "fetch_date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query_topics": topics,
        "time_window_days": days,
        "papers": list(all_papers.values()),
        "total_count": len(all_papers),
    }

    return result


def save_digest(digest: dict) -> Path:
    """保存到 data/paper_watch/YYYY-MM-DD.json"""
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    output_path = WATCH_DIR / f"{date}.json"
    output_path.write_text(
        json.dumps(digest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def show_summary() -> None:
    """显示今日已有摘要"""
    date = datetime.now().strftime("%Y-%m-%d")
    json_path = WATCH_DIR / f"{date}.json"

    if not json_path.exists():
        print(f"📭 今日 ({date}) 尚无论文摘要。")
        print("  请运行: python fetch_papers.py")
        return

    data = json.loads(json_path.read_text(encoding="utf-8"))
    papers = data.get("papers", [])

    print(f"## 📰 论文追踪摘要 ({date})\n")
    print(f"**搜索关键词**: {', '.join(data.get('query_topics', []))}")
    print(f"**时间窗口**: 最近 {data.get('time_window_days', '?')} 天")
    print(f"**论文数量**: {data.get('total_count', 0)}\n")

    if not papers:
        print("未找到新论文。")
        return

    print("| # | 标题 | 作者 | 发表日期 | arXiv ID |")
    print("|:---|:---|:---|:---|:---|")
    for i, p in enumerate(papers, 1):
        authors_str = ", ".join(p.get("authors", [])[:2])
        if len(p.get("authors", [])) > 2:
            authors_str += " et al."
        print(f"| {i} | {p['title'][:60]}{'...' if len(p['title']) > 60 else ''} | {authors_str} | {p['published']} | [{p['arxiv_id']}](https://arxiv.org/abs/{p['arxiv_id']}) |")


def main():
    parser = argparse.ArgumentParser(
        description="ScholarMind Paper Watch — 论文追踪",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--action", default="fetch", choices=["fetch", "summary"],
                        help="fetch: 抓取新论文; summary: 显示今日摘要")
    parser.add_argument("--topics", help="逗号分隔的搜索关键词 (不指定则从 USER.md 读取)")
    parser.add_argument("--days", type=int, default=7, help="最近 N 天 (默认 7)")
    parser.add_argument("--max-results", type=int, default=5, help="每个关键词最多返回数 (默认 5)")
    args = parser.parse_args()

    if args.action == "summary":
        show_summary()
        return

    # 加载关键词
    if args.topics:
        topics = [t.strip() for t in args.topics.split(",")]
    else:
        topics = load_topics_from_user_md()
        if not topics:
            print("❌ 未找到搜索关键词。请使用 --topics 指定，或在 memory/USER.md 中配置研究方向。")
            sys.exit(1)
        print(f"📋 从 USER.md 读取关键词: {', '.join(topics)}")

    print(f"⏳ 正在搜索最近 {args.days} 天的论文...\n")

    # 抓取
    digest = fetch_all(topics, max_results=args.max_results, days=args.days)

    # 保存
    output_path = save_digest(digest)

    print(f"\n✅ 论文追踪完成!")
    print(f"   📊 找到 {digest['total_count']} 篇论文")
    print(f"   📁 保存到: {output_path}")

    # 简要预览
    if digest["papers"]:
        print(f"\n📰 前 5 篇:")
        for i, p in enumerate(digest["papers"][:5], 1):
            print(f"   {i}. [{p['published']}] {p['title'][:70]}")


if __name__ == "__main__":
    main()
