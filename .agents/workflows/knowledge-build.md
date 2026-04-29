---
description: 从多篇论文中构建知识图谱，检测知识盲区，并生成个性化学习路径
---

# Knowledge Build (知识构建) Workflow

用于从多篇论文中积累知识并分析学习需求的工作流。

## 前置准备

- 读取 `memory/USER.md` 了解用户研究方向
- 读取 `memory/MEMORY.md` 了解已有经验

## 步骤

1. **检查当前图谱状态**:
   - 使用 `knowledge-graph` MCP 工具：调用 `get_graph_stats`
   - 如果为空，引导用户先使用 `/paper-analysis` 分析论文

2. **批量添加论文** (针对每篇论文重复):
   - 如果用户有 PDF：使用 paper_reader skill 提取文本，然后调用 `add_paper_to_graph`
   - 如果用户只有论文标题：先使用 `paper-search` 找到它们

3. **回顾图谱增长**:
   - 再次调用 `get_graph_stats` 以显示进度
   - 调用 `query_knowledge` 查询核心概念

4. **运行知识盲区检测**:
   ```bash
   python skills/learning_path/scripts/analyze_knowledge.py --action detect_gaps
   ```

5. **生成学习路径**:
   ```bash
   python skills/learning_path/scripts/analyze_knowledge.py --action learning_path
   ```

6. **获取概念重要性排名**:
   ```bash
   python skills/learning_path/scripts/analyze_knowledge.py --action importance --top 10
   ```

7. **展示整合报告**:
   - 图谱健康度指标
   - 附带严重程度的知识盲区 Top 排名
   - 推荐的学习路径（关键 → 重要 → 补充）
   - 建议下一步阅读的论文（基于盲区推荐）

8. **建议下一步操作**:
   - 对于基础盲区 (foundation_gaps): "建议阅读综述论文补充基础"
   - 对于孤立概念 (isolated_concepts): "建议寻找关联论文建立知识连接"
   - 对于单一来源 (single_source): "建议从其他论文交叉验证"

9. **经验归档** (自动):
   如果本次任务中有值得记录的经验，请更新记忆文件：
   - 图谱构建中发现的技巧 → 追加到 `memory/MEMORY.md`
   - 用户新的研究兴趣 → 更新 `memory/USER.md`
   - **预算约束**: MEMORY.md 超过 800 Token 时，删除最旧条目
