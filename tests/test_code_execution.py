from __future__ import annotations

"""
ScholarMind - 代码执行模块测试
=================================

测试覆盖：
1. 沙箱基础执行（print, 数学计算）
2. 安全检查（危险模式检测）
3. 超时控制
4. 模板管理（列表、获取、参数覆盖）
5. matplotlib 图表自动保存
6. 错误处理（语法错误、运行时错误）
"""

import pytest
from pathlib import Path

from src.execution.sandbox import (
    CodeSandbox,
    ExecutionResult,
    check_code_safety,
)
from src.execution.templates import (
    list_templates,
    get_template,
    get_template_code,
    TEMPLATES,
    CodeTemplate,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sandbox(tmp_path):
    """使用临时目录的沙箱"""
    return CodeSandbox(work_dir=tmp_path / "sandbox", timeout=10)


# ============================================================
# Tests: 安全检查
# ============================================================

class TestSafetyCheck:

    def test_safe_code(self):
        warnings = check_code_safety("import numpy as np\nprint(np.ones(3))")
        assert warnings == []

    def test_detects_os_system(self):
        warnings = check_code_safety("import os\nos.system('ls')")
        assert any("os.system" in w for w in warnings)

    def test_detects_subprocess(self):
        warnings = check_code_safety("import subprocess")
        assert any("subprocess" in w for w in warnings)

    def test_detects_eval(self):
        warnings = check_code_safety("result = eval('1+1')")
        assert any("eval" in w for w in warnings)

    def test_detects_exec(self):
        warnings = check_code_safety("exec('print(1)')")
        assert any("exec" in w for w in warnings)

    def test_detects_rmtree(self):
        warnings = check_code_safety("import shutil\nshutil.rmtree('/tmp')")
        assert any("rmtree" in w for w in warnings)

    def test_numpy_scipy_safe(self):
        code = """
import numpy as np
from scipy.fft import fft
import matplotlib.pyplot as plt
x = np.linspace(0, 2*np.pi, 100)
print(np.sin(x).mean())
"""
        warnings = check_code_safety(code)
        assert warnings == []


# ============================================================
# Tests: 沙箱执行
# ============================================================

class TestSandboxExecution:

    def test_simple_print(self, sandbox):
        result = sandbox.execute("print('hello world')")
        assert result.success is True
        assert "hello world" in result.stdout
        assert result.return_code == 0

    def test_math_calculation(self, sandbox):
        result = sandbox.execute("print(2 ** 10)")
        assert result.success is True
        assert "1024" in result.stdout

    def test_numpy_code(self, sandbox):
        code = "import numpy as np\nprint(np.array([1,2,3]).sum())"
        result = sandbox.execute(code)
        assert result.success is True
        assert "6" in result.stdout

    def test_syntax_error(self, sandbox):
        result = sandbox.execute("print('unclosed string")
        assert result.success is False
        assert result.return_code != 0

    def test_runtime_error(self, sandbox):
        result = sandbox.execute("x = 1/0")
        assert result.success is False
        assert "ZeroDivision" in result.stderr

    def test_timeout(self, sandbox):
        """无限循环应该超时"""
        result = sandbox.execute("while True: pass", timeout=2)
        assert result.success is False
        assert "超时" in result.error_message

    def test_execution_time_recorded(self, sandbox):
        result = sandbox.execute("print(1)")
        assert result.execution_time > 0

    def test_result_to_markdown(self, sandbox):
        result = sandbox.execute("print('test output')")
        md = result.to_markdown()
        assert "执行成功" in md
        assert "test output" in md

    def test_security_warning_in_result(self, sandbox):
        """有安全警告但仍能执行"""
        result = sandbox.execute("print('safe code')")
        # 这段代码是安全的，不应有警告
        assert result.security_warnings == []

    def test_matplotlib_figure_saved(self, sandbox):
        """matplotlib 图表应自动保存为 PNG"""
        code = """
import matplotlib.pyplot as plt
plt.figure()
plt.plot([1, 2, 3], [1, 4, 9])
plt.title('Test')
"""
        result = sandbox.execute(code)
        assert result.success is True
        # 检查是否生成了 PNG 文件
        assert any(f.endswith(".png") for f in result.output_files)


# ============================================================
# Tests: 模板管理
# ============================================================

class TestTemplates:

    def test_templates_registered(self):
        assert len(TEMPLATES) >= 3

    def test_ofdm_template_exists(self):
        t = get_template("ofdm_basic")
        assert t is not None
        assert t.category == "communication"

    def test_mimo_template_exists(self):
        t = get_template("mimo_beamforming")
        assert t is not None

    def test_music_template_exists(self):
        t = get_template("aoa_music")
        assert t is not None

    def test_list_all_templates(self):
        templates = list_templates()
        assert len(templates) >= 3

    def test_list_by_category(self):
        comm = list_templates("communication")
        assert all(t.category == "communication" for t in comm)
        assert len(comm) >= 2

    def test_get_nonexistent_template(self):
        assert get_template("nonexistent") is None

    def test_get_template_code(self):
        code = get_template_code("ofdm_basic")
        assert code is not None
        assert "OFDM" in code
        assert "import numpy" in code

    def test_template_has_all_fields(self):
        for name, t in TEMPLATES.items():
            assert t.name, f"Template {name} missing name"
            assert t.title, f"Template {name} missing title"
            assert t.description, f"Template {name} missing description"
            assert t.category, f"Template {name} missing category"
            assert t.code, f"Template {name} missing code"
            assert t.parameters, f"Template {name} missing parameters"
            assert t.difficulty in ("easy", "medium", "hard"), \
                f"Template {name} invalid difficulty: {t.difficulty}"


# ============================================================
# Tests: 模板执行（集成）
# ============================================================

class TestTemplateExecution:

    def test_ofdm_runs(self, sandbox):
        """OFDM 模板应该能完整执行"""
        code = get_template_code("ofdm_basic")
        result = sandbox.execute(code, timeout=30)
        assert result.success is True
        assert "BER" in result.stdout

    def test_music_runs(self, sandbox):
        """MUSIC 模板应该能完整执行"""
        code = get_template_code("aoa_music")
        result = sandbox.execute(code, timeout=30)
        assert result.success is True
        assert "MUSIC" in result.stdout
