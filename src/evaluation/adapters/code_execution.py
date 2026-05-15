from __future__ import annotations

"""
code_execution adapter —— 封装代码执行沙箱能力。

CodeSandbox 直接构造在 ctx.sandbox.sandbox_dir 下，与真实 data/sandbox/ 隔离。
完全离线可跑。
"""

from .base import AdapterContext, ToolCallResult, register_adapter


def _result_raw(exec_result) -> dict:
    return {
        "success": exec_result.success,
        "stdout": exec_result.stdout,
        "stderr": exec_result.stderr,
        "return_code": exec_result.return_code,
        "execution_time": exec_result.execution_time,
        "output_files": list(exec_result.output_files),
        "error_message": exec_result.error_message,
        "security_warnings": list(exec_result.security_warnings),
    }


@register_adapter("run_code")
async def run_code(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """在隔离沙箱中执行 Python 代码。"""
    from src.execution.sandbox import CodeSandbox

    code = args.get("code", "")
    timeout = int(args.get("timeout", 30))
    sandbox = CodeSandbox(work_dir=ctx.sandbox.sandbox_dir.resolve(), timeout=timeout)
    exec_result = sandbox.execute(code, timeout=timeout)
    raw = _result_raw(exec_result)
    ok = bool(exec_result.success)
    return ToolCallResult(
        ok=ok, tool="run_code", raw=raw,
        text=f"run_code: success={ok}, rc={exec_result.return_code}, "
             f"{len(exec_result.output_files)} files",
        error="" if ok else (exec_result.error_message or exec_result.stderr[:300]),
        error_category="" if ok else "tool_exception",
    )


@register_adapter("run_template")
async def run_template(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """运行一个科研代码模板。"""
    from src.execution.sandbox import CodeSandbox
    from src.execution.templates import get_template, get_template_code

    name = args.get("template_name", "")
    overrides = args.get("parameter_overrides", {}) or {}
    if get_template(name) is None:
        return ToolCallResult.failure(
            "run_template", f"unknown template: {name}", "tool_exception",
        )
    code = get_template_code(name, **overrides)
    if not code:
        return ToolCallResult.failure(
            "run_template", f"template {name} produced no code", "tool_exception",
        )
    timeout = int(args.get("timeout", 60))
    sandbox = CodeSandbox(work_dir=ctx.sandbox.sandbox_dir.resolve(), timeout=timeout)
    exec_result = sandbox.execute(code, timeout=timeout, skip_safety_check=True)
    raw = _result_raw(exec_result)
    raw["template_name"] = name
    ok = bool(exec_result.success)
    return ToolCallResult(
        ok=ok, tool="run_template", raw=raw,
        text=f"run_template {name}: success={ok}, "
             f"{len(exec_result.output_files)} files",
        error="" if ok else (exec_result.error_message or exec_result.stderr[:300]),
        error_category="" if ok else "tool_exception",
    )


@register_adapter("list_code_templates")
async def list_code_templates(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """列出可用代码模板。"""
    from src.execution.templates import list_templates

    category = args.get("category", "")
    templates = list_templates(category)
    return ToolCallResult(
        ok=True, tool="list_code_templates",
        raw={"success": True, "templates": [
            {"name": t.name, "title": t.title, "category": t.category,
             "difficulty": t.difficulty}
            for t in templates
        ]},
        text=f"{len(templates)} templates" + (f" in category {category}" if category else ""),
    )
