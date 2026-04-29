# ScholarMind - 学术研究 Agent

## 项目概述

ScholarMind 是面向通信感知（ISAC/6G）领域的多模态学术研究 Agent，支持 Antigravity / Claude Code 等 MCP 宿主。

## 架构概览

```
宿主 Agent (Antigravity / Claude Code)
├── CLAUDE.md                     ← 项目入口（你正在读的这个文件）
├── mcp_config.example.json       ← MCP Server 注册模板
└── AcademicAgent/
    ├── memory/                   ← 记忆系统（Hermes/MemU 文件系统范式）
    │   ├── MEMORY.md             ← 经验记忆（≤800 Token，新进旧出）
    │   ├── USER.md               ← 用户画像（≤500 Token）
    │   └── experiences/          ← 决策层经验（搜索策略、解析模式）
    ├── skills/                   ← 2 个 Skill (paper_reader, learning_path)
    ├── .agents/workflows/        ← 3 个 Workflow (paper-analysis, knowledge-build, simulation)
    ├── src/mcp_servers/          ← 3 个 MCP Server (paper_search, knowledge_graph, code_execution)
    └── src/{core,knowledge,execution}/  ← 底层模块
```

## 记忆系统

在每次会话开始时，请读取以下文件以获取持久上下文：

- **用户画像**: 读取 `memory/USER.md` 了解用户研究方向和偏好
- **经验记忆**: 读取 `memory/MEMORY.md` 了解已知的搜索策略和问题
- **搜索经验**: 参考 `memory/experiences/search_strategies.md` 选择最优 API
- **知识导出**: 用户想浏览知识库时，引导查看 `memory/knowledge_export/`

### 经验归档规则

在 Workflow 执行完成后，如果遇到了以下情况，请更新记忆文件：
- API 报错后成功的备选策略 → 更新 `memory/MEMORY.md` 搜索策略章节
- 论文解析中发现的特殊处理技巧 → 更新 `memory/MEMORY.md` 解析经验章节
- 用户偏好变化 → 更新 `memory/USER.md`

**预算约束**: MEMORY.md ≤ 800 Token, USER.md ≤ 500 Token。新增内容时，删除最旧的条目保持预算。

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
