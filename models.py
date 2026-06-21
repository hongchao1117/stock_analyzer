"""共享数据模型 — 所有模块使用的 dataclass 统一定义."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class StockInfo:
    """单只股票的基础信息（解析后）."""

    input_symbol: str          # 用户输入的原始代码，如 "513100"
    normalized_symbol: str     # yfinance 标准格式，如 "513100.SS"
    market: str                # "CN" | "US" | "HK"
    name: str | None = None    # 从行情数据获取的名称（解析时未知）
    components: list[str] = field(default_factory=list)  # 主要成分股（ETF时使用）

    @property
    def is_etf(self) -> bool:
        """判断是否为ETF（基于代码规则：A股51开头，或名称含ETF）。"""
        if self.market == "CN" and self.input_symbol.startswith("51"):
            return True
        if self.name and "ETF" in self.name.upper():
            return True
        return False


@dataclass
class MarketSnapshot:
    """单只股票的行情快照."""

    symbol: str                # normalized symbol
    name: str                  # 股票名称
    market: str                # "CN" | "US" | "HK"
    price: float
    change_pct: float          # 涨跌幅 (%)
    change_amount: float       # 涨跌额
    volume: int
    prev_close: float
    data_time: str             # 行情数据时间字符串
    market_status: str         # "盘中" | "已收盘" | "未知"
    timezone: str              # "Asia/Shanghai" | "America/New_York" 等


@dataclass
class NewsItem:
    """处理后的新闻条目."""

    title: str
    summary: str               # 摘要（截断到120字）
    source: str                # 来源
    url: str
    published: str             # 发布日期字符串
    sentiment: str             # "positive" | "negative" | "neutral"
    sentiment_score: float     # 情感分数，正=利好，负=利空
    affected_symbols: list[str] = field(default_factory=list)  # 影响的 normalized symbols
    relevance_score: float = 0.0   # 0.0-1.0 最高相关度
    importance: str = "medium"     # "high" | "medium" | "low"
    search_keyword: str = ""       # 触发该新闻的搜索关键词（调试用）


@dataclass
class StockAdvice:
    """单只股票的操作建议."""

    symbol: str                # normalized symbol
    name: str
    action: str                # "hold" | "watch" | "accumulate" | "reduce"
    confidence: str            # "high" | "medium" | "low"
    reasons: list[str] = field(default_factory=list)
    risk_note: str | None = None
    # 可追溯数据
    price_change_pct: float = 0.0
    sentiment_bias: str = "neutral"  # "bullish" | "neutral" | "bearish"
    related_news_count: int = 0


@dataclass
class DailyBriefing:
    """每日简报."""

    date: str
    disclaimer: str
    data_status: str           # "live" | "mock" | "partial"
    data_status_label: str     # 人类可读标签
    snapshots: list[MarketSnapshot] = field(default_factory=list)
    news_items: list[NewsItem] = field(default_factory=list)
    advice: list[StockAdvice | None] = field(default_factory=list)
    dropped_news: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # 非致命错误信息
    theme: str | None = None


ACTION_LABELS: dict[str, str] = {
    "hold": "持有",
    "watch": "关注",
    "accumulate": "加仓",
    "reduce": "减仓",
}

ACTION_EMOJI: dict[str, str] = {
    "hold": "📦",
    "watch": "👀",
    "accumulate": "📈",
    "reduce": "📉",
}

CONFIDENCE_LABELS: dict[str, str] = {
    "high": "高",
    "medium": "中",
    "low": "低",
}

SENTIMENT_EMOJI: dict[str, str] = {
    "positive": "🟢",
    "negative": "🔴",
    "neutral": "🟡",
}

MARKET_LABELS: dict[str, str] = {
    "CN": "A股",
    "US": "美股",
    "HK": "港股",
}
