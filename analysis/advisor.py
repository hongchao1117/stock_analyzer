"""操作建议生成器 — 二维决策矩阵: 行情涨跌 × 消息面多空.

综合单只股票的行情变化和相关新闻的情感偏向，给出操作建议。
每条建议可追溯到具体的行情数据或新闻。
"""

from __future__ import annotations

from dataclasses import dataclass

from models import (
    MarketSnapshot, NewsItem, StockInfo, StockAdvice,
    SENTIMENT_EMOJI,
)

# ═══════════════════════════════════════════════════════════
# 可配置阈值
# ═══════════════════════════════════════════════════════════


@dataclass
class Thresholds:
    """分析阈值配置."""

    big_up: float = 3.0          # 大涨阈值 (%)
    big_down: float = -3.0       # 大跌阈值 (%)
    attention: float = 1.5       # 关注阈值 (%)
    sentiment_bullish: float = 0.3    # 消息面偏多阈值
    sentiment_bearish: float = -0.3   # 消息面偏空阈值


# ═══════════════════════════════════════════════════════════
# 决策矩阵
# ═══════════════════════════════════════════════════════════
#
# 行 = 行情分桶: big_up | small_up | flat | small_down | big_down
# 列 = 消息面:   bullish | neutral | bearish
#
# 值 = (action, confidence)
#   action:     hold(持有) | watch(关注) | accumulate(加仓) | reduce(减仓)
#   confidence: high | medium | low

DECISION_MATRIX: dict[tuple[str, str], tuple[str, str]] = {
    # (price_bucket, sentiment_bias) → (action, confidence)

    # 大涨 + 偏多 → 加仓（顺势而为）
    ("big_up", "bullish"): ("accumulate", "high"),
    # 大涨 + 中性 → 持有
    ("big_up", "neutral"): ("hold", "high"),
    # 大涨 + 偏空 → 关注风险（消息与走势背离，警惕）
    ("big_up", "bearish"): ("watch", "medium"),

    # 小涨 + 偏多 → 持有
    ("small_up", "bullish"): ("hold", "medium"),
    # 小涨 + 中性 → 持有
    ("small_up", "neutral"): ("hold", "high"),
    # 小涨 + 偏空 → 关注
    ("small_up", "bearish"): ("watch", "medium"),

    # 震荡 + 偏多 → 关注（可能蓄力突破）
    ("flat", "bullish"): ("watch", "medium"),
    # 震荡 + 中性 → 持有
    ("flat", "neutral"): ("hold", "high"),
    # 震荡 + 偏空 → 关注
    ("flat", "bearish"): ("watch", "medium"),

    # 小跌 + 偏多 → 关注（可能是抄底机会）
    ("small_down", "bullish"): ("watch", "medium"),
    # 小跌 + 中性 → 持有
    ("small_down", "neutral"): ("hold", "medium"),
    # 小跌 + 偏空 → 持有（观望，不做激进操作）
    ("small_down", "bearish"): ("hold", "medium"),

    # 大跌 + 偏多 → 关注抄底（基本面好，技术面超卖）
    ("big_down", "bullish"): ("accumulate", "medium"),
    # 大跌 + 中性 → 关注
    ("big_down", "neutral"): ("watch", "medium"),
    # 大跌 + 偏空 → 减仓（基本面+技术面双杀）
    ("big_down", "bearish"): ("reduce", "high"),
}


def bucket_price(change_pct: float, t: Thresholds) -> str:
    """将涨跌幅分桶.

    Returns:
        "big_up" | "small_up" | "flat" | "small_down" | "big_down"
    """
    if change_pct >= t.big_up:
        return "big_up"
    if change_pct >= t.attention:
        return "small_up"
    if change_pct > -t.attention:
        return "flat"
    if change_pct > t.big_down:
        return "small_down"
    return "big_down"


def bucket_sentiment(positive: int, negative: int, total: int) -> str:
    """计算消息面倾向分桶.

    Args:
        positive: 利好新闻数
        negative: 利空新闻数
        total: 相关新闻总数

    Returns:
        "bullish" | "neutral" | "bearish"
    """
    if total == 0:
        return "neutral"
    bias = (positive - negative) / total

    if bias > 0.3:
        return "bullish"
    if bias < -0.3:
        return "bearish"
    return "neutral"


def generate_reasons(
    stock: StockInfo,
    snapshot: MarketSnapshot,
    news_items: list[NewsItem],
    sentiment_bias: str,
    action: str,
) -> list[str]:
    """生成1-2条人类可读的建议理由.

    Args:
        stock: 股票信息
        snapshot: 行情快照
        news_items: 相关新闻列表
        sentiment_bias: 消息面倾向
        action: 建议动作

    Returns:
        理由文本列表
    """
    reasons: list[str] = []
    name = snapshot.name or stock.input_symbol
    change_pct = snapshot.change_pct

    # 行情理由
    if change_pct >= 0:
        direction = "上涨"
    else:
        direction = "下跌"

    abs_pct = abs(change_pct)
    if abs_pct >= 3.0:
        magnitude = "大幅"
    elif abs_pct >= 1.5:
        magnitude = ""
    else:
        magnitude = "微"

    reasons.append(f"{name}今日{magnitude}{direction}{abs_pct:.1f}%")

    # 消息面理由
    if news_items:
        pos_count = sum(1 for n in news_items if n.sentiment == "positive")
        neg_count = sum(1 for n in news_items if n.sentiment == "negative")

        if sentiment_bias == "bullish":
            bias_text = "偏多"
        elif sentiment_bias == "bearish":
            bias_text = "偏空"
        else:
            bias_text = "中性"

        reasons.append(
            f"消息面{bias_text}（{pos_count}利好/{neg_count}利空/{len(news_items)}条相关）"
        )

        # 额外：提到最重要的那条新闻
        important_news = [n for n in news_items if n.importance == "high"]
        if important_news and len(reasons) < 2:
            # 替换或追加关键新闻
            top_news = important_news[0]
            emoji = SENTIMENT_EMOJI.get(top_news.sentiment, "")
            reasons.append(f"{emoji} 关键: {top_news.title[:60]}...")

    # 截断到最多2条理由
    return reasons[:2]


def generate_one(
    stock: StockInfo,
    snapshot: MarketSnapshot,
    news_items: list[NewsItem],
    thresholds: Thresholds | None = None,
) -> StockAdvice:
    """为单只股票生成操作建议.

    Args:
        stock: 股票信息
        snapshot: 行情快照（必须有效，price > 0）
        news_items: 与该股票相关的所有新闻（已过滤的）
        thresholds: 阈值配置

    Returns:
        StockAdvice
    """
    if thresholds is None:
        thresholds = Thresholds()

    # 1. 行情分桶
    price_bucket = bucket_price(snapshot.change_pct, thresholds)

    # 2. 消息面统计
    pos_count = sum(1 for n in news_items if n.sentiment == "positive")
    neg_count = sum(1 for n in news_items if n.sentiment == "negative")
    total = len(news_items)
    sentiment_bias = bucket_sentiment(pos_count, neg_count, total)

    # 3. 查决策矩阵
    key = (price_bucket, sentiment_bias)
    action, confidence = DECISION_MATRIX.get(key, ("hold", "low"))

    # 4. 特殊情况修正
    risk_note = None

    # 如果行情数据本身是占位数据（获取失败），降低置信度
    if snapshot.price <= 0:
        confidence = "low"
        risk_note = "行情数据不可用，建议仅供参考"

    # 如果没有任何相关新闻，降低置信度
    if total == 0:
        if confidence == "high":
            confidence = "medium"
        risk_note = (risk_note or "") + " 当日无相关消息面数据"

    # 5. 生成理由
    reasons = generate_reasons(stock, snapshot, news_items, sentiment_bias, action)

    # 6. 构造结果
    return StockAdvice(
        symbol=stock.normalized_symbol,
        name=snapshot.name or stock.input_symbol,
        action=action,
        confidence=confidence,
        reasons=reasons,
        risk_note=risk_note.strip() if risk_note else None,
        price_change_pct=snapshot.change_pct,
        sentiment_bias=sentiment_bias,
        related_news_count=total,
    )


def generate_all(
    stocks: list[StockInfo],
    snapshots: list[MarketSnapshot],
    news_items: list[NewsItem],
    thresholds: Thresholds | None = None,
) -> list[StockAdvice | None]:
    """为所有股票生成操作建议.

    Args:
        stocks: 已解析的股票列表
        snapshots: 与 stocks 一一对应的行情快照
        news_items: 所有新闻（内部按 affected_symbols 分发）
        thresholds: 阈值配置

    Returns:
        与 stocks 一一对应的建议列表。行情获取失败的返回 None。
    """
    if thresholds is None:
        thresholds = Thresholds()

    # 按 normalized_symbol 索引新闻
    news_by_symbol: dict[str, list[NewsItem]] = {}
    for news in news_items:
        for sym in news.affected_symbols:
            if sym not in news_by_symbol:
                news_by_symbol[sym] = []
            news_by_symbol[sym].append(news)

    results: list[StockAdvice | None] = []
    for stock, snapshot in zip(stocks, snapshots):
        if snapshot.price <= 0 and snapshot.market_status == "未知":
            # 行情完全不可用 → 返回 None
            results.append(None)
            continue

        related = news_by_symbol.get(stock.normalized_symbol, [])
        advice = generate_one(stock, snapshot, related, thresholds)
        results.append(advice)

    return results
