#!/usr/bin/env python3
"""
ScholarMind 一键安装脚本
========================

自动完成以下操作：
1. 检测项目根目录
2. 检查 Python 依赖
3. 生成 mcp_config.json（填入真实路径）
4. 创建 .env 文件（如果不存在）
5. 创建 data/ 目录
6. 输出注册指南

Usage:
    python install.py
"""

import json
import os
import shutil
import sys
from pathlib import Path

# Fix Windows GBK encoding: force UTF-8 for stdout/stderr
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main():
    print("=" * 60)
    print("  ScholarMind 安装向导")
    print("=" * 60)
    print()

    # Step 1: 检测项目根目录
    project_root = Path(__file__).parent.resolve()
    # 统一使用正斜杠，兼容 Windows/Linux/macOS
    project_root_str = str(project_root).replace("\\", "/")
    print(f"📁 项目根目录: {project_root_str}")
    print()

    # Step 2: 检查关键文件是否存在
    required_files = [
        "src/mcp_servers/paper_search.py",
        "src/mcp_servers/knowledge_graph.py",
        "src/mcp_servers/code_execution.py",
        "skills/paper_reader/SKILL.md",
        "skills/learning_path/SKILL.md",
        "requirements.txt",
    ]
    missing = [f for f in required_files if not (project_root / f).exists()]
    if missing:
        print("❌ 缺少关键文件:")
        for f in missing:
            print(f"   - {f}")
        print("\n请确保你已完整克隆仓库。")
        sys.exit(1)
    print("✅ 关键文件检查通过")

    # Step 3: 创建 data/ 目录
    data_dir = project_root / "data"
    images_dir = project_root / "data" / "scholarmind_images"
    data_dir.mkdir(exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    print("✅ data/ 目录已创建")

    # Step 4: 创建 .env（如果不存在）
    env_file = project_root / ".env"
    env_example = project_root / ".env.example"
    if not env_file.exists() and env_example.exists():
        shutil.copy(env_example, env_file)
        print("✅ .env 文件已从 .env.example 复制")
        print("   ⚠️  请编辑 .env 填入你的 MINIMAX_API_KEY")
    elif env_file.exists():
        print("✅ .env 文件已存在")
    else:
        print("⚠️  未找到 .env.example，请手动创建 .env")

    # Step 5: 生成 mcp_config.json
    template_file = project_root / "mcp_config.example.json"
    output_file = project_root / "mcp_config.json"

    if template_file.exists():
        template_content = template_file.read_text(encoding="utf-8")
        config_content = template_content.replace("<PROJECT_ROOT>", project_root_str)
        output_file.write_text(config_content, encoding="utf-8")
        print(f"✅ mcp_config.json 已生成")
    else:
        # 如果模板不存在，直接构建
        config = {
            "mcpServers": {
                "paper-search": {
                    "command": "python",
                    "args": [f"{project_root_str}/src/mcp_servers/paper_search.py"],
                    "env": {"PYTHONPATH": project_root_str},
                },
                "knowledge-graph": {
                    "command": "python",
                    "args": [f"{project_root_str}/src/mcp_servers/knowledge_graph.py"],
                    "env": {
                        "PYTHONPATH": project_root_str,
                        "SCHOLARMIND_DATA_DIR": f"{project_root_str}/data",
                    },
                },
                "code-execution": {
                    "command": "python",
                    "args": [f"{project_root_str}/src/mcp_servers/code_execution.py"],
                    "env": {
                        "PYTHONPATH": project_root_str,
                        "SCHOLARMIND_DATA_DIR": f"{project_root_str}/data",
                    },
                },
            }
        }
        output_file.write_text(
            json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"✅ mcp_config.json 已生成")

    # Step 6: 输出注册指南
    print()
    print("=" * 60)
    print("  📋 下一步：将 MCP Server 注册到你的宿主")
    print("=" * 60)
    print()
    print("方法 A: Antigravity (Gemini)")
    print(f"  将 {output_file} 的内容合并到:")
    print("  ~/.gemini/antigravity/mcp_config.json")
    print()
    print("方法 B: Claude Code")
    print(f"  将 {output_file} 的内容合并到:")
    print("  ~/.claude/mcp_config.json")
    print()
    print("方法 C: 其他 MCP 宿主")
    print("  参考你的宿主文档，注册 stdio 类型的 MCP Server。")
    print(f"  配置文件: {output_file}")
    print()
    print("🎉 安装完成！")
    print()
    print("快速验证:")
    print(f"  python {project_root_str}/src/mcp_servers/paper_search.py")
    print("  (如果没有报错，说明 MCP Server 可以正常启动)")


if __name__ == "__main__":
    main()
