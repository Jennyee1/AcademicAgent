---
description: 追踪近期新论文 — 抓取 arXiv 最新论文，LLM 智能筛选并推荐
---

# Paper Watch (论文追踪) Workflow

追踪特定领域的最新论文，由 LLM 筛选并推荐最相关的论文。

## 前置准备

- 读取 `memory/USER.md` 了解用户研究方向
- 读取 `memory/MEMORY.md` 了解搜索经验

## 步骤

1. **抓取近期论文** (如果今日未运行过):
   ```bash
   python skills/paper_watch/scripts/fetch_papers.py --days 7
   ```
   如果用户指定了特定主题，可用 `--topics` 参数覆盖：
   ```bash
   python skills/paper_watch/scripts/fetch_papers.py --topics "ISAC,RIS" --days 3
   ```

2. **读取今日摘要**:
   ```bash
   python skills/paper_watch/scripts/fetch_papers.py --action summary
   ```

3. **LLM 智能筛选**:
   - 根据 `memory/USER.md` 中的研究方向，从今日摘要中筛选 Top 5 最相关论文
   - 对每篇推荐论文生成：
     - 📌 一句话概括
     - 🔗 与用户研究方向的关联度（高/中/低）
     - 📎 arXiv 链接

4. **推荐与引导**:
   - 以表格形式展示 Top 5 推荐
   - 询问："要深入分析某篇吗？" → 引导至 `/paper-analysis` Workflow
   - 询问："要调整追踪的关键词吗？" → 更新 `memory/USER.md`

5. **经验归档** (自动):
   - 如果搜索关键词需要调整 → 更新 `memory/USER.md`
   - 如果发现搜索策略经验 → 更新 `memory/MEMORY.md`
   - **预算约束**: MEMORY.md 超过 800 Token 时，删除最旧条目
