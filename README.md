# 🧠 ScholarMind

> 面向通信感知领域的多模态学术研究 Agent — 可安装到任何 MCP 宿主（Antigravity / Claude Code 等）

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/Protocol-MCP-green.svg)](https://modelcontextprotocol.io/)

## ✨ Feature 亮点

| 功能 | 描述 |
|:---|:---|
| 🔍 **论文搜索** | 双源搜索（Semantic Scholar + arXiv），429 自动降级 |
| 📊 **多模态理解** | 理解论文中的图表、公式和系统框图（按需触发，控制 Token） |
| 🕸️ **知识图谱** | 阅读论文自动构建个人学术知识网络（Pydantic Schema 约束） |
| 🎯 **学习规划** | 基于知识盲区检测（PageRank），智能推荐学习路径 |
| 💻 **代码复现** | 将论文方法转化为可执行的仿真代码（沙箱隔离） |

## 🏗️ Architecture

```
ScholarMind/
├── CLAUDE.md                   ← 宿主入口文档
├── install.py                  ← 一键安装脚本
├── mcp_config.example.json     ← MCP 注册模板
├── memory/                     ← 记忆系统（Hermes/MemU 文件系统范式）
│   ├── MEMORY.md               ← 经验记忆（≤800 Token，新进旧出）
│   ├── USER.md                 ← 用户画像（≤500 Token）
│   ├── experiences/            ← 决策层经验（搜索策略、解析模式）
│   └── knowledge_export/       ← 图谱可读导出（自动生成）
├── .agents/workflows/          ← 3 个 Workflow (SOP 剧本)
│   ├── paper-analysis.md       ← /paper-analysis
│   ├── knowledge-build.md      ← /knowledge-build
│   └── simulation.md           ← /simulation
├── skills/                     ← 2 个 Skill (操作手册 + CLI 脚本)
│   ├── paper_reader/           ← 论文解析 (PDF → 文本 + 图片)
│   └── learning_path/          ← 学习路径 (盲区检测 + 路径规划)
├── src/
│   ├── mcp_servers/            ← 3 个 MCP Server (常驻进程)
│   │   ├── paper_search.py     ← 论文搜索 (Semantic Scholar + arXiv)
│   │   ├── knowledge_graph.py  ← 知识图谱管理
│   │   └── code_execution.py   ← 代码沙箱执行
│   ├── core/                   ← 核心引擎
│   │   ├── pdf_parser.py       ← PDF 解析 (PyMuPDF, Generator 模式)
│   │   └── multimodal.py       ← 图表分析 (Strategy 模式)
│   ├── knowledge/              ← 知识图谱模块
│   │   ├── schema.py           ← Pydantic + Enum Schema (含 Zep 时间维度)
│   │   ├── extractor.py        ← LLM 知识抽取 (Structured Output)
│   │   ├── graph_store.py      ← NetworkX 图存储 + TF-IDF 语义检索 + Markdown 导出
│   │   └── graph_analyzer.py   ← PageRank 图分析引擎
│   └── execution/              ← 仿真执行模块
│       ├── sandbox.py          ← 安全沙箱 (subprocess 隔离)
│       └── templates.py        ← OFDM/MIMO/MUSIC 仿真模板
├── prompts/                    ← Prompt 模板库
└── tests/                      ← 测试套件
```

## 🚀 Quick Start

### 1. 克隆 & 安装依赖

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

这会自动：
- 检查关键文件完整性
- 创建 `data/` 目录
- 从模板生成 `mcp_config.json`（自动填入你的项目路径）
- 输出注册到宿主的指南

### 4. 注册到宿主

将生成的 `mcp_config.json` 内容合并到你的宿主配置：

| 宿主 | 配置文件位置 |
|:---|:---|
| Antigravity | `~/.gemini/antigravity/mcp_config.json` |
| Claude Code | `~/.claude/mcp_config.json` |

### 5. 开始使用

```
> "帮我搜索关于 ISAC channel estimation 的最新论文"
> /paper-analysis
> /knowledge-build
```

## 🛠️ Tech Stack

| 类别 | 技术 |
|:---|:---|
| **协议** | MCP (Model Context Protocol) |
| **PDF 解析** | PyMuPDF (Generator 模式, 防 OOM) |
| **知识图谱** | NetworkX + Pydantic Structured Output + Zep 时间维度 |
| **检索** | TF-IDF 语义检索 (ReMe hybrid retrieval) + 关键词回退 |
| **搜索** | Semantic Scholar API + arXiv API (自动降级) |
| **记忆** | Hermes-style MEMORY.md + USER.md + MemU Markdown 导出 |
| **仿真** | subprocess 沙箱 + numpy/scipy |

## 🧠 Memory System

借鉴 Hermes Agent、ReMe、MemU、Zep 等记忆框架思想，实现了轻量级文件系统记忆：

| 记忆层 | 实现 | 灵感来源 |
|:---|:---|:---|
| 用户画像 | `memory/USER.md` (≤500 Token) | Mem0 用户建模 |
| 经验记忆 | `memory/MEMORY.md` (≤800 Token，新进旧出) | Hermes MEMORY.md + ReMe |
| 时间维度 | `schema.py` 时间字段 | Zep/Graphiti 时序图谱 |
| 语义检索 | `graph_store.py` TF-IDF | ReMe hybrid retrieval |
| 可审计导出 | `export_to_markdown()` | MemU 文件系统记忆 |

## 📝 License

MIT
