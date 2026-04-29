---
description: 端到端的论文分析 — 搜索、下载、解析、提取知识，并生成学习建议
---

# Paper Analysis (论文分析) Workflow

从零开始分析一篇学术论文的完整工作流。

## 前置准备

- 读取 `memory/USER.md` 了解用户研究方向
- 读取 `memory/MEMORY.md` 了解已有搜索经验和已知问题

## 步骤

1. **搜索论文** (如果用户本地没有):
   - 使用 `paper-search` MCP 工具：带上主题参数调用 `search_papers`
   - 参考 `memory/experiences/search_strategies.md` 选择最优 API
   - 如果用户需要特定的某篇论文，使用 Paper ID 调用 `get_paper_details`
   - 记录结果中的 PDF 链接

2. **下载 PDF** (如果需要):
   ```bash
   curl -L -o data/paper.pdf "<pdf_url>"
   ```

3. **获取论文元数据并检查是否为扫描版**:
   ```bash
   python skills/paper_reader/scripts/parse_pdf.py --action metadata --pdf "<pdf_path>"
   ```

4. **提取论文结构**:
   ```bash
   python skills/paper_reader/scripts/parse_pdf.py --action structure --pdf "<pdf_path>"
   ```

5. **向用户展示结构概览** 并询问需要重点关注哪些章节。

6. **提取全文** 以供知识图谱使用:
   ```bash
   python skills/paper_reader/scripts/parse_pdf.py --action text --pdf "<pdf_path>"
   ```

7. **分析关键图表** (仅在用户明确要求时):
   - 提取图片: `--action images --page <N>`
   - 或者渲染整页: `--action render --page <N>`
   - 对保存的图片使用 `view_file`，以便调用视觉能力进行分析

8. **添加至知识图谱**:
   - 使用 `knowledge-graph` MCP 工具：将提取的文本作为参数调用 `add_paper_to_graph`
   - 使用 `get_graph_stats` 检查图谱统计信息

9. **生成研究报告** (持久化论文解读):
   - 将步骤 6 提取的全文保存为临时文件（如 `data/temp_text.txt`）
   - 生成结构化报告：
   ```bash
   python src/report/generator.py --title "<paper_title>" --text-file data/temp_text.txt --year "<year>" --arxiv-id "<arxiv_id>"
   ```
   - 报告自动保存到 `data/reports/papers/`（JSON + HTML 双格式）
   - 向用户展示 HTML 报告路径，建议用浏览器打开查看

10. **建议下一步操作**:
    - "需要分析更多图表吗？"
    - "要查看学习路径建议吗？" → 建议运行 `/knowledge-build`
    - "要用仿真验证论文方法吗？" → 建议运行 `/simulation`

11. **经验归档** (自动):
    如果本次任务中遇到了以下情况之一，请更新记忆文件：
    - API 报错或限流 → 追加到 `memory/MEMORY.md` 搜索策略章节，并更新 `memory/experiences/search_strategies.md`
    - 论文解析的特殊处理技巧 → 追加到 `memory/MEMORY.md` 解析经验章节
    - 用户偏好变化 → 更新 `memory/USER.md`
    - **预算约束**: MEMORY.md 超过 800 Token 时，删除最旧条目
    - 格式：`- [YYYY-MM-DD] 描述。建议：...`
