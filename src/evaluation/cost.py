from __future__ import annotations

"""
成本估算 —— 基于 token 的单次任务成本。

PRICE_TABLE 是 git 跟踪的价格表（USD / 1K tokens）。adapter 优先从 API
response 填 tokens_in/out（method="api_usage"）；拿不到时由 adapter 用
字符数估算（method="char_heuristic"）。两种来源都会被诚实地记录，
避免把粗略估算包装成精确数字。
"""

from dataclasses import dataclass

# USD / 1K tokens —— 估算用途，非财务结算口径。
# MiniMax 公开价格较低，外部检索 API（Semantic Scholar / arXiv）免费。
PRICE_TABLE: dict[str, dict[str, float]] = {
    "MiniMax-Text-01": {"input": 0.0002, "output": 0.0011},
    "MiniMax-VL-01": {"input": 0.0002, "output": 0.0011},
    "_default": {"input": 0.0002, "output": 0.0011},
    "_free": {"input": 0.0, "output": 0.0},
}


@dataclass
class CostEstimate:
    usd: float
    tokens_in: int
    tokens_out: int
    method: str  # "api_usage" | "char_heuristic" | "free" | "none"
    model: str = ""

    def to_dict(self) -> dict:
        return {
            "usd": round(self.usd, 6),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "method": self.method,
            "model": self.model,
        }


def price_for(model: str) -> dict[str, float]:
    return PRICE_TABLE.get(model, PRICE_TABLE["_default"])


def estimate_cost(
    tokens_in: int,
    tokens_out: int,
    model: str = "_default",
    method: str = "char_heuristic",
) -> CostEstimate:
    """根据 token 数与价格表估算成本。"""
    if tokens_in == 0 and tokens_out == 0:
        return CostEstimate(usd=0.0, tokens_in=0, tokens_out=0,
                            method="none", model=model)
    price = price_for(model)
    usd = (tokens_in / 1000.0) * price["input"] + (tokens_out / 1000.0) * price["output"]
    return CostEstimate(
        usd=usd, tokens_in=tokens_in, tokens_out=tokens_out,
        method=method, model=model,
    )


def chars_to_tokens(text: str) -> int:
    """粗略：约 4 字符 / token。"""
    return max(0, len(text or "") // 4)
