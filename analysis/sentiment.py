"""情感分析引擎 — 中英双语关键词规则 + 否定句式处理 + 标的映射.

Phase 1: 纯规则引擎（零依赖、零成本、可解释）
Phase 2 预留: analyze_with_llm() 接口
"""

from __future__ import annotations

import logging
import hashlib

from models import NewsItem, StockInfo

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# 情感词典
# ═══════════════════════════════════════════════════════════

# 中文利好词 (带权重)
POSITIVE_CN: dict[str, int] = {
    "突破": 3, "创新高": 3, "暴涨": 2, "涨停": 2,
    "利好": 2, "增长": 2, "合作": 2, "量产": 3,
    "订单": 2, "上调": 2, "超预期": 3, "获批": 2,
    "补贴": 2, "政策支持": 2, "回购": 2, "分红": 2,
    "盈利": 2, "扩张": 2, "融资": 1, "上市": 1,
    "领涨": 2, "反弹": 1, "企稳": 1, "回暖": 1,
    "研发成功": 3, "中标": 2, "签约": 2, "新品发布": 2,
    "产能提升": 2, "市场份额": 1, "业绩预增": 3,
}

# 中文利空词 (带权重)
NEGATIVE_CN: dict[str, int] = {
    "制裁": -3, "限制": -2, "禁令": -3, "暴跌": -2,
    "跌停": -2, "亏损": -2, "裁员": -2, "调查": -2,
    "诉讼": -2, "罚款": -2, "下调": -2, "低于预期": -3,
    "贸易战": -3, "退市": -3, "违约": -3, "暴雷": -3,
    "造假": -3, "停产": -2, "召回": -2, "收紧": -2,
    "监管": -1, "处罚": -2, "警示": -1, "风险": -1,
    "下滑": -2, "萎缩": -2, "衰退": -2, "需求疲软": -2,
    "关税": -2, "出口管制": -3, "列入实体清单": -3,
    "出口审查": -2, "扩大审查": -2, "反垄断": -2, "加征关税": -3,
}

# 英文利好词
POSITIVE_EN: dict[str, int] = {
    "breakthrough": 3, "record high": 3, "rally": 2,
    "upgrade": 2, "beat": 2, "beat estimates": 3,
    "partnership": 2, "launch": 1, "approval": 2,
    "expansion": 2, "buyback": 2, "dividend": 2,
    "outperform": 2, "surge": 2, "soar": 2,
    "growth": 2, "profit": 1, "revenue growth": 2,
    "bullish": 2, "upside": 2, "strong demand": 3,
    "raised guidance": 3, "record revenue": 3,
}

# 英文利空词
NEGATIVE_EN: dict[str, int] = {
    "sanction": -3, "restriction": -2, "ban": -3,
    "plunge": -2, "decline": -2, "crash": -3,
    "investigation": -2, "lawsuit": -2, "fine": -2,
    "downgrade": -2, "miss": -1, "miss estimates": -3,
    "layoff": -2, "recall": -2, "probe": -2,
    "penalty": -2, "delist": -3, "default": -3,
    "fraud": -3, "probe": -2, "tariff": -2,
    "export control": -3, "entity list": -3,
    "bearish": -2, "downside": -2, "weak demand": -3,
    "lowered guidance": -3, "loss": -2, "debt": -1,
}

# 否定前缀（出现在这些词前面时，反转紧跟的情感词）
NEGATION_CN: set[str] = {
    "不会", "难以", "有限", "未必", "不可能", "不至于",
    "远未", "并非", "不存在", "没有", "无", "并未",
}

NEGATION_EN: set[str] = {
    "unlikely", "not", "won't", "no", "limited",
    "no sign of", "far from", "doesn't", "don't",
    "isn't", "aren't", "wasn't", "weren't", "cannot",
}

# 情感分类阈值
SENTIMENT_BULLISH_THRESHOLD = 0.3
SENTIMENT_BEARISH_THRESHOLD = -0.3


def sentiment_score(title: str, summary: str) -> tuple[float, str]:
    """计算单条新闻的情感分数和标签.

    使用子串匹配而非分词匹配，以正确处理中英文混合文本。
    中文没有空格分词，所以直接在原文中搜索情感词并定位。

    Args:
        title: 新闻标题
        summary: 新闻摘要

    Returns:
        (score, label) — score 为浮点数（正=利好，负=利空），label ∈ {"positive", "negative", "neutral"}
    """
    text = f"{title}。{summary}"
    text_lower = text.lower()
    text_len = len(text)
    total_score: float = 0.0

    # 收集所有命中位置: (start_pos, end_pos, weight)
    hits: list[tuple[int, int, float]] = []

    # ---- 扫描中文情感词 ----
    for word, weight in POSITIVE_CN.items():
        pos = 0
        while True:
            idx = text.find(word, pos)
            if idx == -1:
                break
            hits.append((idx, idx + len(word), float(weight)))
            pos = idx + 1

    for word, weight in NEGATIVE_CN.items():
        pos = 0
        while True:
            idx = text.find(word, pos)
            if idx == -1:
                break
            hits.append((idx, idx + len(word), float(weight)))
            pos = idx + 1

    # ---- 扫描英文情感词（大小写不敏感） ----
    for word, weight in POSITIVE_EN.items():
        pos = 0
        while True:
            idx = text_lower.find(word, pos)
            if idx == -1:
                break
            hits.append((idx, idx + len(word), float(weight)))
            pos = idx + 1

    for word, weight in NEGATIVE_EN.items():
        pos = 0
        while True:
            idx = text_lower.find(word, pos)
            if idx == -1:
                break
            hits.append((idx, idx + len(word), float(weight)))
            pos = idx + 1

    if not hits:
        return 0.0, "neutral"

    # 按位置排序
    hits.sort(key=lambda h: h[0])

    # ---- 检查否定 ----
    # 收集否定词位置
    negation_positions: list[int] = []
    for neg_word in NEGATION_CN:
        pos = 0
        while True:
            idx = text.find(neg_word, pos)
            if idx == -1:
                break
            negation_positions.append(idx)
            pos = idx + 1
    for neg_word in NEGATION_EN:
        pos = 0
        while True:
            idx = text_lower.find(neg_word, pos)
            if idx == -1:
                break
            negation_positions.append(idx)
            pos = idx + 1

    negation_positions.sort()

    def _is_negated(hit_start: int) -> bool:
        """检查 hit 前 N 个字符内是否有否定词."""
        window_start = max(0, hit_start - 15)  # ~5个中文字符
        for neg_pos in negation_positions:
            if window_start <= neg_pos < hit_start:
                return True
        return False

    # ---- 计算得分 ----
    for start, end, weight in hits:
        if _is_negated(start):
            total_score -= weight  # 反转
        else:
            total_score += weight

    # 按文本长度归一化（每100个字符）
    normalized_score = total_score / (text_len / 100)

    # 分类
    if normalized_score > SENTIMENT_BULLISH_THRESHOLD:
        label = "positive"
    elif normalized_score < SENTIMENT_BEARISH_THRESHOLD:
        label = "negative"
    else:
        label = "neutral"

    return round(normalized_score, 2), label


def map_to_symbols(
    title: str,
    summary: str,
    stocks: list[StockInfo],
) -> tuple[list[str], float]:
    """判断新闻影响哪些持仓标的.

    匹配策略:
    1. 股票名称直接出现 → relevance = 1.0
    2. 预置关键词出现 → relevance = 0.7
    3. 公司名（ETF权重股）出现 → relevance = 0.6
    4. 无匹配 → relevance = 0.0

    Args:
        title: 新闻标题
        summary: 新闻摘要
        stocks: 持仓股票列表

    Returns:
        (affected_normalized_symbols, max_relevance_score)
    """
    text = f"{title} {summary}".lower()
    affected: list[str] = []
    max_relevance = 0.0

    for stock in stocks:
        relevance = 0.0
        stock_name = (stock.name or "").lower()
        symbol = stock.input_symbol.lower()

        # 股票名称直接出现
        if stock_name and stock_name in text:
            relevance = max(relevance, 1.0)

        # 股票代码出现（如 AAPL）
        if symbol in text.split():  # 必须是独立词（避免 "AAPL" 匹配 "AAPL's" 的边界情况）
            relevance = max(relevance, 0.9)

        # ETF 关键词匹配
        for component in stock.components:
            if component.lower() in text:
                relevance = max(relevance, 0.6)

        if relevance > 0:
            affected.append(stock.normalized_symbol)
            max_relevance = max(max_relevance, relevance)

    return affected, max_relevance


def analyze_batch(
    articles: list[dict],
    stocks: list[StockInfo],
) -> tuple[list[NewsItem], list[dict]]:
    """批量分析新闻：情感打分 + 标的映射 + 过滤.

    Args:
        articles: 原始文章 dict 列表
        stocks: 持仓股票列表

    Returns:
        (news_items, dropped_news)
        - news_items: 通过过滤的新闻（有情感标签 + 有影响的标的）
        - dropped_news: 被过滤的新闻 + 丢弃原因
    """
    news_items: list[NewsItem] = []
    dropped: list[dict] = []

    for article in articles:
        title = article.get("title", "")
        summary = article.get("summary", "")

        # 情感分析
        score, label = sentiment_score(title, summary)

        # 标的映射
        affected_symbols, relevance = map_to_symbols(title, summary, stocks)

        # 过滤条件
        drop_reason = None
        if not affected_symbols:
            drop_reason = f"与持仓标的无关: {title[:50]}..."
        elif relevance < 0.3:
            drop_reason = f"相关度过低 ({relevance:.2f}): {title[:50]}..."

        if drop_reason:
            dropped.append({
                "title": title,
                "reason": drop_reason,
                "source": article.get("source", ""),
                "url": article.get("url", ""),
            })
            continue

        # 构造 NewsItem
        news_id = hashlib.md5(
            (article.get("url", "") + title).encode()
        ).hexdigest()[:12]

        # 重要度判断
        if abs(score) > 3 or relevance > 0.8:
            importance = "high"
        elif abs(score) > 1 or relevance > 0.5:
            importance = "medium"
        else:
            importance = "low"

        news_items.append(NewsItem(
            title=title,
            summary=summary[:120],
            source=article.get("source", ""),
            url=article.get("url", ""),
            published=article.get("published", ""),
            sentiment=label,
            sentiment_score=score,
            affected_symbols=affected_symbols,
            relevance_score=relevance,
            importance=importance,
            search_keyword=article.get("search_keyword", ""),
        ))

    # 按相关度 + 重要度排序
    news_items.sort(
        key=lambda n: (
            0 if n.importance == "high" else 1 if n.importance == "medium" else 2,
            -n.relevance_score,
            -abs(n.sentiment_score),
        )
    )

    logger.info(
        "情感分析完成: %d 条通过, %d 条被过滤",
        len(news_items), len(dropped),
    )

    return news_items, dropped


# ---- LLM 接口预留 ----
def analyze_with_llm(
    articles: list[dict],
    stocks: list[StockInfo],
    model: str = "claude-sonnet-4-6",
) -> tuple[list[NewsItem], list[dict]]:
    """(Phase 2) 使用 LLM 进行语义级情感分析.

    MVP 阶段暂未实现。此接口预留给后续增强。
    """
    raise NotImplementedError(
        "LLM 情感分析模式暂未实现。"
        "请使用默认的关键词规则引擎（不传 --llm 参数）。"
    )
