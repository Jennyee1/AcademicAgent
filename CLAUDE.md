# ScholarMind - 学术研究 Agent

## 项目概述

ScholarMind 是面向通信感知（ISAC/6G）领域的多模态学术研究 Agent，已嵌入 Antigravity 框架。

## 架构概览

```
Antigravity (宿主 Agent)
├── ~/.gemini/GEMINI.md          ← 角色定义 + 领域规则
├── ~/.gemini/antigravity/
│   └── mcp_config.json          ← 3 个 MCP Server 注册
└── AcademicAgent/
    ├── skills/                   ← 2 个 Skill (paper_reader, learning_path)
    ├── .agents/workflows/        ← 3 个 Workflow (paper-analysis, knowledge-build, simulation)
    ├── src/mcp_servers/          ← 3 个 MCP Server (paper_search, knowledge_graph, code_execution)
    └── src/{core,knowledge,execution}/  ← 底层模块
```

## 快速使用

- **搜索论文**: 直接说 "帮我搜索 ISAC channel estimation 的论文"
- **分析论文**: 说 "帮我分析这篇 PDF" 或使用 `/paper-analysis`
- **知识积累**: 使用 `/knowledge-build` 工作流
- **仿真实验**: 使用 `/simulation` 工作流

## 详细文档

- 角色与规则: `~/.gemini/GEMINI.md`
- Skills: `skills/paper_reader/SKILL.md` , `skills/learning_path/SKILL.md`
- Workflows: `.agents/workflows/*.md`
- 项目文档: `docs/`

## 代码规范

- Python 代码遵循 PEP 8，使用 type hints
- 科学计算优先使用 numpy / scipy
- 通信仿真使用 numpy + scipy.signal
