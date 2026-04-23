from __future__ import annotations

import sys
from pathlib import Path as _Path
_PROJECT_ROOT = _Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

"""
ScholarMind - 代码执行 MCP Server
=====================================

功能：
  1. run_code           — 在沙箱中执行 Python 代码
  2. run_template       — 运行预置模板（可修改参数）
  3. list_templates     — 列出可用的代码模板
  4. explain_template   — 详细解释模板的功能和参数

技术架构：
  用户: "帮我用 OFDM 模板跑个仿真"
    ↓
  Claude Code → MCP Protocol → 本 Server
    ├── templates.py (代码模板库)
    └── sandbox.py (安全执行沙箱)
    ↓
  subprocess 隔离执行 → 收集输出 + 图表

【工程思考】代码执行为什么是重要的 Phase 4？
  Phase 1-3 让 Agent 能"读懂论文"和"规划学习"，
  Phase 4 让 Agent 能"动手实验"——这是从"被动学习"到"主动验证"的跨越。
  面试亮点：Agent 不只是 chatbot，它能真正帮你跑仿真。
"""

import logging
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from src.execution.sandbox import CodeSandbox
from src.execution.templates import (
    list_templates as _list_templates,
    get_template,
    get_template_code,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ScholarMind.CodeExecution")

# ============================================================
# 全局实例
# ============================================================
import os
DATA_DIR = Path(os.getenv("SCHOLARMIND_DATA_DIR", str(Path(__file__).parent.parent.parent / "data")))
SANDBOX_DIR = DATA_DIR / "sandbox"

mcp = FastMCP(
    "ScholarMind-CodeExecution",
    instructions=(
        "代码执行与实验复现服务。"
        "可以安全地运行 Python 仿真代码，提供通信领域预置模板，"
        "帮助研究生将论文方法快速转化为可运行的实验。"
    ),
)

sandbox = CodeSandbox(work_dir=SANDBOX_DIR, timeout=30)


# ============================================================
# MCP Tools
# ============================================================

@mcp.tool()
async def run_code(
    code: str,
    timeout: int = 30,
    description: str = "",
) -> str:
    """
    在安全沙箱中执行 Python 代码。

    适合使用的场景：
    - 用户说"帮我跑一下这段代码"
    - 用户说"验证一下这个公式的数值结果"
    - 需要运行仿真代码并获取结果和图表
    - 论文方法的快速原型验证

    支持的库：numpy, scipy, matplotlib, math
    自动保存 matplotlib 图表到文件。

    Args:
        code: 要执行的 Python 代码
        timeout: 超时秒数（最大 120）
        description: 代码功能描述（用于日志）

    Returns:
        执行结果报告（包含输出、错误、图表文件路径）
    """
    logger.info(f"代码执行请求: {description or '(无描述)'}, timeout={timeout}s")

    if not code.strip():
        return "⚠️ 代码为空，请提供要执行的 Python 代码。"

    result = sandbox.execute(code, timeout=timeout)
    return result.to_markdown()


@mcp.tool()
async def run_template(
    template_name: str,
    parameter_overrides: str = "",
) -> str:
    """
    运行预置的通信领域代码模板。

    适合使用的场景：
    - 用户说"用 OFDM 模板跑个仿真"
    - 用户说"帮我试试 MUSIC 算法"
    - 需要快速验证通信/信号处理概念
    - 论文中提到某个方法，想快速看效果

    可用模板：
    - ofdm_basic: OFDM 基础收发机（QPSK + BER 曲线）
    - mimo_beamforming: MIMO 波束赋形（MRT vs ZF 对比）
    - aoa_music: MUSIC 算法 AOA 估计

    Args:
        template_name: 模板名称（如 "ofdm_basic"）
        parameter_overrides: 参数覆盖，格式 "key1=value1, key2=value2"
                            例如 "N_sc=128, CP_len=32"

    Returns:
        执行结果报告
    """
    logger.info(f"模板执行请求: {template_name}, overrides='{parameter_overrides}'")

    template = get_template(template_name)
    if not template:
        available = ", ".join(t.name for t in _list_templates())
        return (
            f"❌ 模板 '{template_name}' 不存在。\n\n"
            f"可用模板: {available}\n\n"
            f"使用 `list_templates` 查看详情。"
        )

    # 解析参数覆盖
    overrides = {}
    if parameter_overrides:
        for pair in parameter_overrides.split(","):
            pair = pair.strip()
            if "=" in pair:
                key, value = pair.split("=", 1)
                overrides[key.strip()] = value.strip()

    code = get_template_code(template_name, **overrides)
    if not code:
        return f"❌ 获取模板代码失败。"

    result = sandbox.execute(code, timeout=60)

    # 在输出前加上模板信息
    header = (
        f"## 📋 模板: {template.title}\n\n"
        f"- **分类**: {template.category}\n"
        f"- **难度**: {template.difficulty}\n"
    )
    if overrides:
        header += f"- **参数覆盖**: {overrides}\n"
    header += "\n"

    return header + result.to_markdown()


@mcp.tool()
async def list_code_templates(category: str = "") -> str:
    """
    列出所有可用的代码模板。

    适合使用的场景：
    - 用户说"有什么模板可以用？"
    - 用户说"通信相关的代码模板有哪些？"
    - 需要查看可用的仿真代码

    Args:
        category: 可选分类过滤（communication / localization / signal_processing）

    Returns:
        模板列表
    """
    templates = _list_templates(category)

    if not templates:
        return f"📭 没有找到{'分类为 ' + category + ' 的' if category else ''}模板。"

    result = "## 📚 代码模板库\n\n"
    result += "| 名称 | 标题 | 分类 | 难度 | 描述 |\n"
    result += "|:---|:---|:---|:---|:---|\n"

    for t in templates:
        result += (
            f"| `{t.name}` | {t.title} | {t.category} | {t.difficulty} | "
            f"{t.description[:80]}... |\n"
        )

    result += (
        f"\n共 **{len(templates)}** 个模板。"
        f"使用 `run_template(template_name)` 运行模板。\n"
    )

    # 分类统计
    cats = Counter(t.category for t in templates)
    result += "\n**分类统计**: " + ", ".join(f"{c}: {n}" for c, n in cats.items())

    return result


@mcp.tool()
async def explain_template(template_name: str) -> str:
    """
    详细解释一个代码模板的功能、参数和用法。

    适合使用的场景：
    - 用户说"OFDM 模板是干什么的？"
    - 用户说"MUSIC 算法模板怎么用？"
    - 需要了解模板的参数才能修改

    Args:
        template_name: 模板名称

    Returns:
        模板详细说明
    """
    template = get_template(template_name)
    if not template:
        return f"❌ 模板 '{template_name}' 不存在。"

    result = f"## 📋 {template.title}\n\n"
    result += f"**分类**: {template.category} | **难度**: {template.difficulty}\n\n"
    result += f"### 描述\n\n{template.description}\n\n"
    result += f"### 可调参数\n\n"
    for param in template.parameters:
        result += f"- `{param}`\n"
    result += (
        f"\n### 使用示例\n\n"
        f"```\n"
        f"# 使用默认参数运行\n"
        f'run_template("{template_name}")\n\n'
        f"# 修改参数运行\n"
        f'run_template("{template_name}", "{template.parameters[0]}=新值")\n'
        f"```\n\n"
    )
    result += f"### 完整代码\n\n```python\n{template.code}\n```"

    return result


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    logger.info("ScholarMind Code Execution MCP Server 启动中...")
    logger.info(f"沙箱目录: {SANDBOX_DIR}")
    logger.info(f"可用模板: {len(_list_templates())} 个")
    mcp.run()
