---
name: learning_path
description: 分析知识图谱以检测知识盲区，并利用 PageRank 和拓扑分析生成个性化学习路径
---

# Learning Path（学习路径）Skill

## 什么时候使用

当用户提出以下需求时使用此 Skill：
- 询问 "我接下来应该学什么？" 或 "帮我规划学习路径"
- 询问 "我哪些知识薄弱？" 或 "我还缺什么？"
- 询问 "哪些概念最重要？" 或 "核心知识有哪些？"
- 想要评估其知识图谱的健康状况

## 前置条件

- 知识图谱必须有数据（请先使用 `get_graph_stats` MCP 工具检查）
- 项目根目录：`e:/Materials/AntiG/AcademicAgent`

## 操作指南

### 1. 生成学习路径

```bash
cd e:/Materials/AntiG/AcademicAgent && python skills/learning_path/scripts/analyze_knowledge.py --action learning_path --focus "<optional_focus_area>" --max-items 15
```

返回完整的学习路径报告，包含：
- 知识图谱健康度指标
- 知识盲区（按严重程度排序）
- 推荐学习路径（按优先级排序：核心 → 重要 → 补充）

### 2. 检测知识盲区

```bash
cd e:/Materials/AntiG/AcademicAgent && python skills/learning_path/scripts/analyze_knowledge.py --action detect_gaps
```

返回三种类型的盲区：
- 🔴 **foundation_gap** (基础盲区): 核心概念（高 PageRank）但属性稀疏
- 🟡 **isolated_concept** (孤立概念): 度 ≤ 1 的概念（未建立联系的知识）
- 🟠 **single_source** (单一来源): 仅从 1 篇论文中了解到的概念（存在潜在偏差）

### 3. 获取概念重要性排名

```bash
cd e:/Materials/AntiG/AcademicAgent && python skills/learning_path/scripts/analyze_knowledge.py --action importance --top 10
```

返回按综合评分排名的概念：`0.4×PageRank + 0.3×degree + 0.2×in_degree + 0.1×betweenness`

## 输出格式

使用脚本返回的 Markdown 格式展示结果：
- 健康度指标：呈现为表格
- 盲区：带有严重程度标识条和可执行的建议
- 学习路径：呈现为带有优先级图标 (🔴/🟡/🟢) 的带编号的表格

## 注意事项

- 如果知识图谱为空，请引导用户先使用 `/paper-analysis` workflow 添加论文
- 如果图谱包含的节点数 < 5，请提醒用户分析结果可能不可靠
- 始终根据发现的盲区提供具体的下一步行动建议
