---
description: 追踪近期新论文 — 抓取 arXiv 最新论文，LLM 智能筛选并推荐
---

# Paper Watch (论文追踪) Workflow

追踪特定领域的最新论文，由 LLM 筛选并推荐最相关的论文。

## 前置准备

- 读取 `memory/USER.md` 了解用户研究方向
- 读取 `memory/MEMORY.md` 了解搜索经验
- **加载历史失败教训**（避坑提示，可选但推荐）：
  ```bash
  python -m src.evaluation.cli lessons --capability retrieval --tool search_arxiv --top 3
  ```
  如果历史卡片显示 rate_limit/timeout 频发，提前在 `fetch_papers.py` 调用间加退避。

## 步骤

1. **抓取近期论文**（**两种模式**任选其一，可叠加）：

   **A. 用户主题模式**（沿用 USER.md / `--topics`）：
   ```bash
   python skills/paper_watch/scripts/fetch_papers.py --days 7
   # 或手动指定主题：
   python skills/paper_watch/scripts/fetch_papers.py --topics "LLM Agent,RAG,multi-agent collaboration" --days 3
   ```

   **B. 盲区驱动模式**（self-improving 闭环：从知识图谱当前盲区自动选题）：
   ```bash
   # 预演：只看会生成哪些 query，不访问 arXiv
   python skills/paper_watch/scripts/gap_driven_watch.py --dry-run

   # 真跑：用 top-N 最严重盲区生成 query 并抓 arXiv
   python skills/paper_watch/scripts/gap_driven_watch.py --top-n 5 --days 7
   ```
   产出的 digest 每篇论文都附 `gap_attributions`，可解释它在补哪个盲区。
   适合在 `/knowledge-build` 跑完后使用，让 Agent 主动给用户推该补的论文。

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
