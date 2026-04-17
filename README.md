# 🧠 ScholarMind

> 面向通信感知领域的多模态学术研究 Agent

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Claude](https://img.shields.io/badge/LLM-Claude_API-orange.svg)](https://www.anthropic.com/)
[![MCP](https://img.shields.io/badge/Protocol-MCP-green.svg)](https://modelcontextprotocol.io/)

## ✨ Feature 亮点

| 功能 | 描述 | 状态 |
|:---|:---|:---|
| 📊 **多模态理解** | 理解论文中的图表、公式和系统框图 | ✅ Phase 1 |
| 🕸️ **知识图谱** | 阅读论文自动构建个人学术知识网络 | ✅ Phase 2 |
| 🎯 **学习规划** | 基于知识盲区检测，智能推荐学习路径 | 🔜 Phase 3 |
| 💻 **代码复现** | 将论文方法转化为可执行的仿真代码 | 🔜 Phase 4 |
| 🔍 **论文搜索** | 双源搜索（Semantic Scholar + arXiv） | ✅ Phase 0 |

## 🏗️ Architecture

```
ScholarMind/
├── CLAUDE.md           ← Claude Code 项目指令
├── src/
│   ├── mcp_servers/    ← MCP 工具服务器
│   │   ├── paper_search.py     ← 论文搜索（Semantic Scholar + arXiv）
│   │   ├── paper_reader.py     ← 论文阅读与多模态分析
│   │   └── knowledge_graph.py  ← 知识图谱管理
│   ├── core/           ← 核心模块
│   │   ├── pdf_parser.py       ← PDF 解析与图表提取
│   │   └── multimodal.py       ← Claude Vision 图表分析
│   ├── knowledge/      ← 知识图谱模块
│   │   ├── schema.py           ← 领域 Schema 定义
│   │   ├── graph_store.py      ← NetworkX 图谱存储
│   │   └── extractor.py        ← LLM 知识抽取
│   └── execution/      ← 代码执行沙箱 (Phase 4)
├── prompts/            ← Prompt 模板库
├── templates/          ← 通信领域代码模板
└── docs/               ← 项目文档
```

## 🚀 Quick Start

### 1. 环境准备

```bash
# 克隆项目
git clone https://github.com/Jennyee1/AcademicAgent.git
cd AcademicAgent

# 创建 Python 环境（推荐 conda）
conda create -n scholarmind python=3.11 -y
conda activate scholarmind

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
# 复制环境变量模板
copy .env.example .env

# 编辑 .env，填入你的 API Key
# 必需：ANTHROPIC_API_KEY
# 推荐：SEMANTIC_SCHOLAR_API_KEY
```

### 3. 使用 MCP Server

```bash
# 方式1：MCP Inspector 交互式测试
mcp dev src/mcp_servers/paper_search.py

# 方式2：注册到 Claude Code
claude mcp add paper-search python src/mcp_servers/paper_search.py

# 方式3：在 Claude Code 中直接使用
claude
# > "帮我搜索关于 ISAC channel estimation 的最新论文"
```

## 📚 文档

| 文档 | 内容 |
|:---|:---|
| [竞品调研](docs/01_竞品调研与市场分析.md) | 现有学术 Agent 分析 |
| [项目设计](docs/02_项目设计与创新点规划.md) | 创新点与技术方案 |
| [开发指南](docs/03_从零开始的Agent开发完全指南.md) | 从零搭建教程 |
| [架构决策](docs/04_技术疑问深度解答与架构决策.md) | 设计决策与技术解答 |
| [工程深度](docs/05_Agent工程落地深度思考.md) | RAG 漏斗模型、防幻觉、生产踩坑 |
| [开发日志](docs/06_项目开发日志.md) | 进度追踪与学习笔记 |
| [技术栈全景](docs/07_技术栈全景与架构决策.md) | 技术栈选型、MCP/RAG/ReAct 架构辨析 |

## 🛠️ Tech Stack

- **LLM**: Claude API (Anthropic)
- **协议**: MCP (Model Context Protocol)
- **PDF 解析**: PyMuPDF
- **向量存储**: ChromaDB
- **知识图谱**: NetworkX → Neo4j
- **代码沙箱**: Docker

## 📝 License

MIT
