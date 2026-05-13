# ScholarMind - 学术研究 Agent

## 项目概述

ScholarMind 是面向大模型 Agent 领域的多模态学术研究 Agent，支持 Antigravity / Claude Code 等 MCP 宿主。它的核心目标是帮助用户围绕 LLM Agent 论文和系统持续积累知识：从检索、阅读、图表理解，到知识图谱构建、学习路径规划和可复现实验。

## 架构概览

```text
宿主 Agent (Antigravity / Claude Code)
├── CLAUDE.md                     <- 项目入口
├── mcp_config.example.json       <- MCP Server 注册模板
└── AcademicAgent/
    ├── memory/                   <- 文件系统记忆
    │   ├── MEMORY.md             <- 经验记忆
    │   ├── USER.md               <- 用户画像
    │   └── experiences/          <- 搜索策略、分析模式等经验
    ├── skills/                   <- paper_reader, learning_path, paper_watch
    ├── .agents/workflows/        <- paper-analysis, knowledge-build, simulation, paper-watch
    ├── src/mcp_servers/          <- paper_search, knowledge_graph, code_execution 等 MCP Server
    └── src/{core,knowledge,execution,report}/
```

## 研究领域

默认围绕大模型 Agent 与学术研究工作流展开，包括但不限于：

- Agent 架构、规划、反思、工具调用和多 Agent 协作
- 长期记忆、RAG、上下文工程、知识图谱和检索增强
- Agent 评测、benchmark、可复现研究和实验闭环
- ReAct、MemGPT、Generative Agents、AutoGen、LangGraph、Toolformer 等代表性论文和系统

## 记忆系统

在每次会话开始时，请读取以下文件以获得持久上下文：

- **用户画像**: 读取 `memory/USER.md` 了解用户研究方向和偏好
- **经验记忆**: 读取 `memory/MEMORY.md` 了解已知搜索策略和问题
- **搜索经验**: 参考 `memory/experiences/search_strategies.md` 选择合适 API
- **知识导出**: 用户想浏览知识库时，引导查看 `memory/knowledge_export/`

### 经验归档规则

Workflow 执行完成后，如果遇到以下情况，请更新记忆文件：

- API 报错后成功的备选策略 -> 更新 `memory/MEMORY.md` 搜索策略章节
- 论文解析中发现的特殊处理技巧 -> 更新 `memory/MEMORY.md` 解析经验章节
- 用户研究偏好变化 -> 更新 `memory/USER.md`

预算约束：`MEMORY.md` 建议控制在 800 token 左右，`USER.md` 建议控制在 500 token 左右。新增内容时，优先删除最旧或不再适用的条目。

## 快速使用

- **搜索论文**: 直接说 "帮我搜索 LLM Agent memory 的最新论文"
- **分析论文**: 说 "帮我分析这篇 PDF" 或使用 `/paper-analysis`
- **知识积累**: 使用 `/knowledge-build` 工作流
- **实验验证**: 使用 `/simulation` 工作流，把论文方法、评测指标或 toy example 转成可运行代码
- **论文追踪**: 使用 `/paper-watch` 跟踪 Agent/RAG/benchmark 等主题的新论文

## 安装

参阅 `README.md` 中的安装指南，或运行：

```bash
pip install -r requirements.txt
python install.py
```

## 详细文档

- Skills: `skills/paper_reader/SKILL.md`, `skills/learning_path/SKILL.md`, `skills/paper_watch/SKILL.md`
- Workflows: `.agents/workflows/*.md`

## 代码规范

- Python 代码遵循 PEP 8，使用 type hints
- 优先复用现有的 MCP 工具、Schema、Prompt 模板和文件系统记忆模式
- 科研实验优先使用 numpy / scipy / matplotlib；面向 Agent 论文时，示例应聚焦规划、记忆、检索、评测和工具调用等概念
