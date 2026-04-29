#!/usr/bin/env python3
"""
ScholarMind - 研究报告生成器
================================

将 LLM 的论文解读结构化保存为 JSON + HTML。

用法（CLI）：
  # 从文本文件生成报告
  python src/report/generator.py --title "论文标题" --text-file data/extracted_text.txt

  # 从 stdin 管道输入
  cat text.txt | python src/report/generator.py --title "论文标题"

  # 指定输出目录
  python src/report/generator.py --title "论文标题" --text-file text.txt --output-dir data/reports/papers

用法（Python API）：
  from src.report.generator import ReportGenerator
  gen = ReportGenerator()
  report = gen.generate(paper_text="...", paper_title="...")
  gen.save(report, output_dir="data/reports/papers")

【工程思考】为什么要 CLI + Python API 双接口？
  - CLI: Workflow 中直接调用（宿主执行 bash 命令）
  - API: 其他模块（如未来的 dashboard.py）程序化调用
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("ScholarMind.ReportGenerator")

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 确保项目根目录在 sys.path 中
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.report.schema import PaperReport, ReportMeta, ReportSummary, REPORT_SCHEMA_DESCRIPTION


# ============================================================
# 报告生成 Prompt
# ============================================================

REPORT_PROMPT = """你是一名通信感知（ISAC/6G）领域的学术论文分析专家。

请仔细阅读下方的论文文本，生成一份结构化的研究报告。

## 报告要求
1. **一句话概括**: 用一句中文精准概括论文核心贡献
2. **问题定义**: 提炼论文要解决的核心问题
3. **贡献列表**: 列出 3-5 条核心贡献，每条简洁有力
4. **方法论**: 描述技术路线（信号模型、算法、架构等）
5. **核心结果**: 总结关键实验结论（包含性能数据）
6. **优缺点**: 客观评价论文的创新性和局限性
7. **与我的关联**: 分析本文与通信感知/ISAC/6G 研究方向的关联

## 论文信息
- **标题**: {paper_title}
- **年份**: {paper_year}

## 论文文本
{text}

## 输出格式
{schema}

严格按照上述 JSON 格式输出，不要输出任何其他解释性文本。
"""


class ReportGenerator:
    """
    LLM 驱动的研究报告生成器

    复用 extractor.py 验证过的 MiniMax API 调用模式：
    - OpenAI 兼容客户端
    - response_format=json_schema 强制输出约束
    - Pydantic model_validate_json 严格解析
    """

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int = 4000,
    ):
        self.model = model or os.getenv("MINIMAX_MODEL", "MiniMax-Text-01")
        self.max_tokens = max_tokens
        self._client = None

    @property
    def client(self):
        """懒加载 OpenAI-compatible client (MiniMax)"""
        if self._client is None:
            from openai import OpenAI
            api_key = os.getenv("MINIMAX_API_KEY")
            base_url = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1")
            if not api_key:
                raise ValueError("MINIMAX_API_KEY 未设置。请在 .env 中配置。")
            self._client = OpenAI(api_key=api_key, base_url=base_url)
        return self._client

    def generate(
        self,
        paper_text: str,
        paper_title: str = "",
        paper_year: str = "",
        authors: list[str] | None = None,
        venue: str = "",
        arxiv_id: str = "",
        pdf_path: str = "",
    ) -> PaperReport:
        """
        调用 LLM 生成结构化研究报告

        Args:
            paper_text: 论文全文（从 paper_reader 提取）
            paper_title: 论文标题
            paper_year: 发表年份
            authors: 作者列表
            venue: 发表会议/期刊
            arxiv_id: arXiv ID
            pdf_path: 本地 PDF 路径

        Returns:
            PaperReport: 结构化报告对象
        """
        # 文本截断（控制 token）
        max_chars = 12000  # 约 3000-4000 token
        if len(paper_text) > max_chars:
            logger.warning(f"论文文本过长 ({len(paper_text)} chars)，截断至 {max_chars}")
            paper_text = paper_text[:max_chars] + "\n\n[... 文本已截断 ...]"

        prompt = REPORT_PROMPT.format(
            paper_title=paper_title or "(未知标题)",
            paper_year=paper_year or "(未知年份)",
            text=paper_text,
            schema=REPORT_SCHEMA_DESCRIPTION,
        )

        logger.info(f"正在生成报告: '{paper_title}'")

        # 调用 LLM
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "paper_report",
                        "schema": PaperReport.model_json_schema(),
                    },
                },
            )
            raw = response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            # 生成一个占位报告
            return self._fallback_report(paper_title, str(e))

        # 解析
        try:
            report = PaperReport.model_validate_json(raw)
        except Exception as e:
            logger.warning(f"Pydantic 解析失败，尝试宽松解析: {e}")
            report = self._loose_parse(raw, paper_title)

        # 补充 meta 信息（LLM 可能没填完整）
        report.meta.paper_title = paper_title or report.meta.paper_title
        if authors:
            report.meta.authors = authors
        if venue:
            report.meta.venue = venue
        if arxiv_id:
            report.meta.arxiv_id = arxiv_id
        if pdf_path:
            report.meta.pdf_path = pdf_path
        if paper_year:
            try:
                report.meta.year = int(paper_year)
            except ValueError:
                pass

        logger.info(f"报告生成成功: {len(report.summary.contributions)} 条贡献, {len(report.tags)} 个标签")
        return report

    def save(
        self,
        report: PaperReport,
        output_dir: str | Path = "data/reports/papers",
    ) -> tuple[Path, Path]:
        """
        保存报告为 JSON + HTML 双格式

        Returns:
            (json_path, html_path)
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 文件名：日期_标题slug
        date = report.meta.generated_at[:10]
        slug = self._slugify(report.meta.paper_title)[:50]
        base_name = f"{date}_{slug}"

        # JSON
        json_path = output_dir / f"{base_name}.json"
        json_path.write_text(
            report.model_dump_json(indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"JSON 报告已保存: {json_path}")

        # HTML
        html_path = output_dir / f"{base_name}.html"
        html_content = self._render_html(report)
        html_path.write_text(html_content, encoding="utf-8")
        logger.info(f"HTML 报告已保存: {html_path}")

        return json_path, html_path

    # ============================================================
    # HTML 渲染
    # ============================================================

    def _render_html(self, report: PaperReport) -> str:
        """
        渲染 HTML 报告

        【工程选择】先用字符串拼接实现，后续迁移到 Jinja2 模板。
        原因：Phase 1A 先跑通完整链路，Phase 4 再用 Jinja2 做高质量模板。
        """
        meta = report.meta
        summary = report.summary

        # 贡献列表
        contributions_html = "".join(
            f"<li>{c}</li>" for c in summary.contributions
        )

        # 优点/缺点
        strengths_html = "".join(f"<li>{s}</li>" for s in summary.strengths) if summary.strengths else "<li>（未分析）</li>"
        weaknesses_html = "".join(f"<li>{w}</li>" for w in summary.weaknesses) if summary.weaknesses else "<li>（未分析）</li>"

        # 图表分析
        figures_html = ""
        if report.figures_analyzed:
            fig_parts = []
            for f in report.figures_analyzed:
                insight_html = '<p class="insight">💡 ' + f.insight + '</p>' if f.insight else ''
                fig_parts.append(
                    f"<div class='figure-item'><h4>{f.figure_id}</h4>"
                    f"<p>{f.description}</p>{insight_html}</div>"
                )
            figures_items = "".join(fig_parts)
            figures_html = f"<section><h2>📊 图表分析</h2>{figures_items}</section>"

        # 标签
        tags_html = " ".join(f"<span class='tag'>{t}</span>" for t in report.tags)

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{meta.paper_title} - 研究报告</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            line-height: 1.8;
            color: #1a1a2e;
            background: linear-gradient(135deg, #667eea11, #764ba211);
            min-height: 100vh;
        }}
        .container {{
            max-width: 860px;
            margin: 0 auto;
            padding: 40px 24px;
        }}
        header {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            padding: 40px 32px;
            border-radius: 16px;
            margin-bottom: 32px;
            box-shadow: 0 8px 32px rgba(102, 126, 234, 0.3);
        }}
        header h1 {{
            font-size: 1.6em;
            margin-bottom: 16px;
            line-height: 1.4;
        }}
        .meta-info {{
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            font-size: 0.9em;
            opacity: 0.9;
        }}
        .meta-info span {{
            background: rgba(255,255,255,0.15);
            padding: 4px 12px;
            border-radius: 20px;
        }}
        .one-sentence {{
            background: #f8f9ff;
            border-left: 4px solid #667eea;
            padding: 20px 24px;
            margin-bottom: 28px;
            border-radius: 0 12px 12px 0;
            font-size: 1.1em;
            font-weight: 500;
            color: #2d3436;
        }}
        section {{
            background: white;
            padding: 28px 32px;
            margin-bottom: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.06);
        }}
        section h2 {{
            font-size: 1.2em;
            margin-bottom: 16px;
            color: #667eea;
            border-bottom: 2px solid #667eea22;
            padding-bottom: 8px;
        }}
        section p {{ margin-bottom: 12px; color: #444; }}
        ul {{ padding-left: 20px; }}
        li {{ margin-bottom: 8px; color: #444; }}
        .strengths {{ border-left: 4px solid #00b894; padding-left: 16px; }}
        .weaknesses {{ border-left: 4px solid #e17055; padding-left: 16px; }}
        .tag {{
            display: inline-block;
            background: #667eea22;
            color: #667eea;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            margin: 4px 4px 4px 0;
        }}
        .figure-item {{
            background: #f8f9ff;
            padding: 16px;
            border-radius: 8px;
            margin-bottom: 12px;
        }}
        .figure-item h4 {{ color: #667eea; }}
        .insight {{ color: #e17055; font-style: italic; }}
        footer {{
            text-align: center;
            margin-top: 32px;
            color: #aaa;
            font-size: 0.85em;
        }}
    </style>
</head>
<body>
<div class="container">
    <header>
        <h1>{meta.paper_title}</h1>
        <div class="meta-info">
            {'<span>👤 ' + ', '.join(meta.authors[:5]) + ('...' if len(meta.authors) > 5 else '') + '</span>' if meta.authors else ''}
            {'<span>📅 ' + str(meta.year) + '</span>' if meta.year else ''}
            {'<span>🏛️ ' + meta.venue + '</span>' if meta.venue else ''}
            {'<span>📎 ' + meta.arxiv_id + '</span>' if meta.arxiv_id else ''}
        </div>
    </header>

    <div class="one-sentence">💡 {summary.one_sentence}</div>

    <section>
        <h2>🎯 问题定义</h2>
        <p>{summary.problem}</p>
    </section>

    <section>
        <h2>🏆 核心贡献</h2>
        <ol>{contributions_html}</ol>
    </section>

    <section>
        <h2>🔬 方法论</h2>
        <p>{summary.methodology}</p>
    </section>

    <section>
        <h2>📈 核心结果</h2>
        <p>{summary.key_results}</p>
    </section>

    <section>
        <h2>⚖️ 评价</h2>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
            <div>
                <h3 style="color: #00b894;">✅ 优点</h3>
                <div class="strengths"><ul>{strengths_html}</ul></div>
            </div>
            <div>
                <h3 style="color: #e17055;">⚠️ 不足</h3>
                <div class="weaknesses"><ul>{weaknesses_html}</ul></div>
            </div>
        </div>
    </section>

    {'<section><h2>🔗 与我的研究关联</h2><p>' + summary.relevance_to_me + '</p></section>' if summary.relevance_to_me else ''}

    {figures_html}

    {'<section><h2>🏷️ 标签</h2><div>' + tags_html + '</div></section>' if report.tags else ''}

    <footer>
        <p>ScholarMind 研究报告 · 生成于 {meta.generated_at[:19]}</p>
    </footer>
</div>
</body>
</html>"""

    # ============================================================
    # 辅助方法
    # ============================================================

    def _slugify(self, text: str) -> str:
        """将标题转为文件名安全的 slug"""
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[\s]+', '_', text.strip())
        return text

    def _fallback_report(self, paper_title: str, error: str) -> PaperReport:
        """LLM 调用失败时的占位报告"""
        return PaperReport(
            meta=ReportMeta(paper_title=paper_title),
            summary=ReportSummary(
                one_sentence=f"[报告生成失败: {error}]",
                problem="",
                contributions=[],
                methodology="",
                key_results="",
            ),
        )

    def _loose_parse(self, raw: str, paper_title: str) -> PaperReport:
        """宽松 JSON 解析（从 LLM 输出中提取 JSON）"""
        # 尝试找到 JSON 块
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return PaperReport.model_validate(data)
            except Exception:
                pass
        return self._fallback_report(paper_title, "JSON 解析失败")


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="ScholarMind 研究报告生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--title", required=True, help="论文标题")
    parser.add_argument("--text-file", help="论文文本文件路径（不指定则从 stdin 读取）")
    parser.add_argument("--year", default="", help="发表年份")
    parser.add_argument("--venue", default="", help="发表会议/期刊")
    parser.add_argument("--arxiv-id", default="", help="arXiv ID")
    parser.add_argument("--output-dir", default="data/reports/papers", help="输出目录")
    args = parser.parse_args()

    # 读取文本
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    if not text.strip():
        print("❌ 输入文本为空", file=sys.stderr)
        sys.exit(1)

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 生成报告
    gen = ReportGenerator()
    report = gen.generate(
        paper_text=text,
        paper_title=args.title,
        paper_year=args.year,
        venue=args.venue,
        arxiv_id=args.arxiv_id,
    )

    # 保存
    json_path, html_path = gen.save(report, output_dir=args.output_dir)

    print(f"\n✅ 研究报告生成完成!")
    print(f"   📄 JSON: {json_path}")
    print(f"   🌐 HTML: {html_path}")


if __name__ == "__main__":
    main()
