from __future__ import annotations

"""
ScholarMind - 安全代码执行沙箱
=================================

核心能力：
  1. 在受限子进程中执行 Python 代码
  2. 超时控制（防止无限循环）
  3. 输出捕获（stdout + stderr + figure 文件）
  4. 工作目录隔离（每次执行在独立目录）

【工程思考】为什么需要代码沙箱？
  - Agent 帮用户把论文方法转成代码后，需要能"跑一下试试"
  - 直接 exec() 太危险（能 import os; os.remove('/')）
  - subprocess 隔离 + 超时 + 工作目录限制 是最实用的 MVP 方案

【安全分析】本沙箱的安全层级：
  Level 1: 子进程隔离（崩溃不影响主进程）         ✅ 已实现
  Level 2: 超时控制（防止无限循环/DoS）            ✅ 已实现
  Level 3: 工作目录隔离（每次执行独立目录）        ✅ 已实现
  Level 4: 危险 import 检测（os.system, shutil 等）  ✅ 已实现
  Level 5: 容器级隔离（Docker sandbox）              ⬜ Phase 5

【设计决策 ADR-009】为什么不用 Docker？
  - 目标是 MVP：学生本机跑仿真代码（numpy/matplotlib/scipy）
  - Docker 增加了部署复杂度（学生需要装 Docker Desktop）
  - 当前方案的安全级别对学术场景已够用
  - 保留 Docker 接口，Phase 5 可升级
"""

import logging
import os
import subprocess
import sys
import tempfile
import time
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ScholarMind.Sandbox")

# ============================================================
# 安全配置
# ============================================================

# 禁止使用的 import / 函数调用（正则匹配源码）
DANGEROUS_PATTERNS = [
    (r'\bos\.system\b', "os.system 禁止使用（命令注入风险）"),
    (r'\bos\.popen\b', "os.popen 禁止使用"),
    (r'\bos\.exec\b', "os.exec* 禁止使用"),
    (r'\bos\.remove\b', "os.remove 禁止使用（文件删除风险）"),
    (r'\bos\.rmdir\b', "os.rmdir 禁止使用"),
    (r'\bos\.unlink\b', "os.unlink 禁止使用"),
    (r'\bshutil\.rmtree\b', "shutil.rmtree 禁止使用"),
    (r'\bsubprocess\b', "subprocess 模块禁止使用"),
    (r'\b__import__\b', "__import__ 禁止使用"),
    (r'\beval\s*\(', "eval() 禁止使用"),
    (r'\bexec\s*\(', "exec() 禁止使用"),
    (r'\bopen\s*\(.*(w|a|x)', "文件写入限制（仅限输出目录）"),
]

# 允许使用的 import（白名单策略的候选，当前为建议模式）
RECOMMENDED_IMPORTS = {
    "numpy", "np",
    "scipy", "scipy.signal", "scipy.linalg", "scipy.fft",
    "matplotlib", "matplotlib.pyplot", "plt",
    "math", "cmath",
    "json", "csv",
    "itertools", "functools", "collections",
    "dataclasses",
    "typing",
}

# 最大执行时间（秒）
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120

# 最大输出长度（字符）
MAX_OUTPUT_LENGTH = 10000


# ============================================================
# 数据类
# ============================================================

@dataclass
class ExecutionResult:
    """
    代码执行结果

    【工程思考】为什么返回结构化结果而不是纯文本？
    1. MCP Server 可以灵活格式化输出
    2. Agent 可以程序化判断执行是否成功
    3. 生成的图表文件路径可以直接用于后续分析
    """
    success: bool
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    execution_time: float = 0.0
    output_files: list[str] = field(default_factory=list)  # 生成的文件路径
    error_message: str = ""
    security_warnings: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        """生成人类可读的执行报告"""
        lines = []

        # 状态
        status = "✅ 执行成功" if self.success else "❌ 执行失败"
        lines.append(f"## {status}\n")
        lines.append(f"- ⏱️ 执行时间: {self.execution_time:.2f}s")
        lines.append(f"- 返回码: {self.return_code}")

        # 安全警告
        if self.security_warnings:
            lines.append(f"\n### ⚠️ 安全警告\n")
            for w in self.security_warnings:
                lines.append(f"- {w}")

        # 标准输出
        if self.stdout:
            output = self.stdout[:MAX_OUTPUT_LENGTH]
            if len(self.stdout) > MAX_OUTPUT_LENGTH:
                output += f"\n... (截断，共 {len(self.stdout)} 字符)"
            lines.append(f"\n### 📤 输出\n\n```\n{output}\n```")

        # 错误输出
        if self.stderr:
            lines.append(f"\n### ⚠️ 错误信息\n\n```\n{self.stderr[:3000]}\n```")

        if self.error_message:
            lines.append(f"\n### 💥 错误\n\n{self.error_message}")

        # 生成的文件
        if self.output_files:
            lines.append(f"\n### 📁 生成的文件\n")
            for f in self.output_files:
                lines.append(f"- `{f}`")

        return "\n".join(lines)


# ============================================================
# 安全检查
# ============================================================

def check_code_safety(code: str) -> list[str]:
    """
    静态安全检查：扫描代码中的危险模式

    【工程思考】为什么不用 AST 分析？
    1. 正则够用：我们要检测的都是简单的函数调用模式
    2. AST 分析更精确但更复杂（需要处理 alias import）
    3. MVP 阶段正则 + 黑名单已够用，Phase 5 可升级到 AST

    Returns:
        安全警告列表（空列表 = 安全）
    """
    warnings = []
    for pattern, message in DANGEROUS_PATTERNS:
        if re.search(pattern, code):
            warnings.append(message)
    return warnings


# ============================================================
# 沙箱执行引擎
# ============================================================

class CodeSandbox:
    """
    安全代码执行沙箱

    Usage:
        sandbox = CodeSandbox()
        result = sandbox.execute("print('hello')")
        print(result.to_markdown())

    【工程思考】执行流程：
    1. 安全检查（静态扫描危险模式）
    2. 注入 matplotlib 非交互后端（避免弹窗）
    3. 写入临时文件
    4. subprocess 执行（超时控制）
    5. 收集输出（stdout + stderr + 生成文件）
    6. 清理临时目录

    【工程思考】为什么用临时文件而不是 -c 参数？
    - 多行代码用 -c 需要转义引号
    - 临时文件支持 import 相对路径
    - 生成的图表文件可以在临时目录中找到
    """

    def __init__(
        self,
        work_dir: Optional[Path] = None,
        timeout: int = DEFAULT_TIMEOUT,
        python_executable: Optional[str] = None,
    ):
        self.work_dir = work_dir or Path(tempfile.gettempdir()) / "scholarmind_sandbox"
        self.timeout = min(timeout, MAX_TIMEOUT)
        self.python_executable = python_executable or sys.executable

        # 确保工作目录存在
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def execute(
        self,
        code: str,
        timeout: Optional[int] = None,
        skip_safety_check: bool = False,
    ) -> ExecutionResult:
        """
        执行 Python 代码

        Args:
            code: Python 代码字符串
            timeout: 超时秒数（覆盖默认值）
            skip_safety_check: 跳过安全检查（仅限可信代码）

        Returns:
            ExecutionResult: 执行结果
        """
        timeout = min(timeout or self.timeout, MAX_TIMEOUT)

        # Step 1: 安全检查
        security_warnings = []
        if not skip_safety_check:
            security_warnings = check_code_safety(code)
            # 有危险模式时，仍然执行但返回警告
            # （学术场景下大部分代码是安全的，不要过度阻塞）
            if security_warnings:
                logger.warning(f"安全检查发现 {len(security_warnings)} 个警告")

        # Step 2: 准备执行环境
        exec_dir = Path(tempfile.mkdtemp(dir=self.work_dir, prefix="exec_"))
        script_path = exec_dir / "main.py"

        # 注入 matplotlib 非交互后端 + 输出目录设置
        preamble = (
            "import matplotlib\n"
            "matplotlib.use('Agg')  # Non-interactive backend\n"
            "import matplotlib.pyplot as plt\n"
            f"import os\n"
            f"os.chdir(r'{exec_dir}')\n"
            "\n"
        )

        full_code = preamble + code

        # 在末尾自动保存所有打开的 figure
        full_code += (
            "\n\n"
            "# Auto-save all open figures\n"
            "import matplotlib.pyplot as _plt\n"
            "for _i, _fig in enumerate(_plt.get_fignums()):\n"
            "    _plt.figure(_fig)\n"
            f"    _plt.savefig(r'{exec_dir}' + f'/figure_{{_i}}.png', dpi=150, bbox_inches='tight')\n"
            "_plt.close('all')\n"
        )

        script_path.write_text(full_code, encoding="utf-8")

        # Step 3: 执行
        start_time = time.time()
        try:
            result = subprocess.run(
                [self.python_executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(exec_dir),
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "MPLBACKEND": "Agg",
                },
            )
            execution_time = time.time() - start_time

            # Step 4: 收集输出文件
            output_files = [
                str(f) for f in exec_dir.iterdir()
                if f.suffix in (".png", ".jpg", ".csv", ".json", ".txt", ".pdf")
                and f.name != "main.py"
            ]

            return ExecutionResult(
                success=(result.returncode == 0),
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                execution_time=execution_time,
                output_files=output_files,
                security_warnings=security_warnings,
            )

        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            return ExecutionResult(
                success=False,
                return_code=-1,
                execution_time=execution_time,
                error_message=f"⏰ 执行超时（{timeout}s）。可能存在无限循环或计算量过大。",
                security_warnings=security_warnings,
            )

        except Exception as e:
            execution_time = time.time() - start_time
            return ExecutionResult(
                success=False,
                return_code=-2,
                execution_time=execution_time,
                error_message=f"执行异常: {type(e).__name__}: {str(e)}",
                security_warnings=security_warnings,
            )
