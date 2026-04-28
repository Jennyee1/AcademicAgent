# ScholarMind - 学术研究 Agent

## 项目概述

ScholarMind 是面向通信感知（ISAC/6G）领域的多模态学术研究 Agent，支持 Antigravity / Claude Code 等 MCP 宿主。

## 架构概览

```
宿主 Agent (Antigravity / Claude Code)
├── CLAUDE.md                     ← 项目入口（你正在读的这个文件）
├── mcp_config.example.json       ← MCP Server 注册模板
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

## 安装

请参阅 `README.md` 中的安装指南，或运行：

```bash
pip install -r requirements.txt
python install.py
```

## 详细文档

- Skills: `skills/paper_reader/SKILL.md` , `skills/learning_path/SKILL.md`
- Workflows: `.agents/workflows/*.md`

## 代码规范

- Python 代码遵循 PEP 8，使用 type hints
- 科学计算优先使用 numpy / scipy
- 通信仿真使用 numpy + scipy.signal
