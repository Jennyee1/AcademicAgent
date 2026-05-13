# ScholarMind

> 面向大模型 Agent 领域的多模态学术研究助手。它可以安装到任意 MCP 宿主中，辅助完成论文检索、PDF/图表理解、知识图谱沉淀、学习路径规划和代码复现实验。

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/Protocol-MCP-green.svg)](https://modelcontextprotocol.io/)

## Feature 亮点

| 功能 | 描述 |
|:---|:---|
| **论文检索** | 双源检索 Semantic Scholar + arXiv，遇到 429 自动降级 |
| **多模态理解** | 解析论文图表、表格、系统架构图和实验曲线，按需触发以控制 token 成本 |
| **知识图谱** | 阅读论文后自动构建个人学术知识网络，使用 Pydantic Schema 约束结构化输出 |
| **学习规划** | 基于知识盲区检测和 PageRank 分析，推荐下一步阅读与补强路径 |
| **代码复现** | 将论文方法转化为可执行的实验或原型代码，并在沙箱中运行验证 |

## 项目定位

ScholarMind 当前聚焦大模型 Agent 研究，适合围绕以下主题建立可持续积累的研究工作流：

- LLM Agent 架构、规划、反思、工具使用和多 Agent 协作
- 长期记忆、RAG、知识图谱和上下文管理
- Agent benchmark、评测闭环、可复现实验和工程框架
- ReAct、MemGPT、Generative Agents、AutoGen、LangGraph 等代表性论文与系统

## Architecture

```text
ScholarMind/
├── CLAUDE.md                   <- 宿主入口文档
├── install.py                  <- 一键安装脚本
├── mcp_config.example.json     <- MCP 注册模板
├── memory/                     <- 文件系统记忆
│   ├── MEMORY.md               <- 经验记忆
│   ├── USER.md                 <- 用户画像
│   ├── experiences/            <- 搜索策略、分析模式等经验
│   └── knowledge_export/       <- 图谱可读导出
├── .agents/workflows/          <- 工作流脚本
│   ├── paper-analysis.md       <- /paper-analysis
│   ├── knowledge-build.md      <- /knowledge-build
│   ├── paper-watch.md          <- /paper-watch
│   └── simulation.md           <- /simulation
├── skills/                     <- Skills 与 CLI 脚本
│   ├── paper_reader/           <- PDF -> 文本 + 图表
│   ├── learning_path/          <- 盲区检测 + 路径规划
│   └── paper_watch/            <- 论文追踪
├── src/
│   ├── mcp_servers/            <- MCP Server
│   ├── core/                   <- PDF 解析、多模态图表分析等核心能力
│   ├── knowledge/              <- 知识图谱 Schema、抽取、存储、分析
│   ├── report/                 <- 结构化研究报告与仪表盘
│   └── execution/              <- 代码沙箱与实验模板
├── prompts/                    <- Prompt 模板库
└── tests/                      <- 测试套件
```

## Quick Start

### 1. 克隆并安装依赖

```bash
git clone https://github.com/Jennyee1/AcademicAgent.git
cd AcademicAgent
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
cp .env.example .env   # Windows: copy .env.example .env
# 编辑 .env，填入 MINIMAX_API_KEY
```

### 3. 一键安装

```bash
python install.py
```

安装脚本会检查关键文件、创建 `data/` 目录、生成 `mcp_config.json`，并输出注册到 MCP 宿主的指引。

### 4. 注册到宿主

将生成的 `mcp_config.json` 内容合并到你的宿主配置：

| 宿主 | 配置文件位置 |
|:---|:---|
| Antigravity | `~/.gemini/antigravity/mcp_config.json` |
| Claude Code | `~/.claude/mcp_config.json` |

### 5. 开始使用

```text
> "帮我搜索关于 LLM Agent memory 的最新论文"
> "分析这篇 ReAct 论文，并把核心概念写入知识图谱"
> /paper-analysis
> /knowledge-build
```

## Tech Stack

| 类别 | 技术 |
|:---|:---|
| **协议** | MCP (Model Context Protocol) |
| **PDF 解析** | PyMuPDF，Generator 模式防 OOM |
| **知识图谱** | NetworkX + Pydantic Structured Output + 时间维度 |
| **检索** | TF-IDF 语义检索 + 关键词回退 |
| **论文搜索** | Semantic Scholar API + arXiv API 自动降级 |
| **记忆** | Hermes-style MEMORY.md + USER.md + Markdown 导出 |
| **实验执行** | subprocess 沙箱 + numpy/scipy/matplotlib |

## Memory System

项目借鉴 Hermes Agent、ReMe、MemU、Zep/Graphiti 等记忆框架，实现轻量级文件系统记忆：

| 记忆层 | 实现 | 灵感来源 |
|:---|:---|:---|
| 用户画像 | `memory/USER.md` | 用户研究偏好建模 |
| 经验记忆 | `memory/MEMORY.md` | Hermes MEMORY.md + ReMe |
| 时间维度 | `schema.py` 时间字段 | Zep/Graphiti 时序图谱 |
| 语义检索 | `graph_store.py` TF-IDF | ReMe hybrid retrieval |
| 可审计导出 | `export_to_markdown()` | MemU 文件系统记忆 |

## GitHub Description 建议

用于仓库简介的一句话可以写成：

```text
A multimodal academic research Agent for LLM Agent papers: search, PDF/figure understanding, knowledge graph memory, learning paths, and reproducible experiments via MCP.
```

## License

MIT
