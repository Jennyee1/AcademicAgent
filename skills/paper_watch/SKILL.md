---
name: paper_watch
description: 追踪特定领域的近期新论文，基于 arXiv API 定时抓取并由 LLM 智能筛选推荐
---

# Paper Watch（论文追踪）Skill

## 什么时候使用

当用户提出以下需求时使用此 Skill：
- "最近有什么新论文？"
- "帮我追踪 ISAC/RIS/... 领域的新进展"
- "今天有新论文推荐吗？"

## 前置条件

- Python 环境，且已安装依赖：`pip install -r requirements.txt`
- `memory/USER.md` 中已记录研究方向（可选，也支持手动指定关键词）

## 操作指南

### 1. 抓取近期论文

从用户研究方向自动读取关键词：

```bash
python skills/paper_watch/scripts/fetch_papers.py
```

手动指定关键词和时间范围：

```bash
python skills/paper_watch/scripts/fetch_papers.py --topics "ISAC,RIS,channel estimation" --days 3
```

参数说明：
- `--topics`: 逗号分隔的搜索关键词（不指定则从 `memory/USER.md` 读取）
- `--days`: 最近 N 天（默认 7）
- `--max-results`: 每个关键词最多返回结果数（默认 5）

输出保存到 `data/paper_watch/YYYY-MM-DD.json`。

### 2. 查看今日摘要

如果今天已经运行过抓取，直接读取今日 JSON：

```bash
python skills/paper_watch/scripts/fetch_papers.py --action summary
```

### 3. LLM 筛选推荐

抓取结果中的论文数量可能很多。请根据 `memory/USER.md` 中的研究方向，**筛选 Top 5 最相关论文**，并生成推荐摘要：

- 标题 + 一句话概括
- 与用户研究方向的关联度（高/中/低）
- "要深入分析这篇论文吗？" → 引导至 `/paper-analysis` Workflow

## 定时运行（可选）

可通过 Windows Task Scheduler 配置每日自动抓取：

```
任务名: ScholarMind-PaperWatch
程序: python
参数: skills/paper_watch/scripts/fetch_papers.py
工作目录: E:\Materials\AntiG\AcademicAgent
触发器: 每日 08:00
```

## 输出格式

- 以表格形式展示推荐论文（标题、作者、发表日期、相关度）
- 每篇论文附带 arXiv 链接
- 如果用户感兴趣，建议下一步使用 `/paper-analysis` 深入分析
