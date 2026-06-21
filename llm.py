"""DeepSeek LLM 集成 — 新闻分析 + 情感判断 + 操作建议.

使用 DeepSeek Chat API 一次性生成新闻摘要、情感分析和操作建议。
API Key 通过环境变量 DEEPSEEK_API_KEY 或 --api-key 参数传入。
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

from models import MarketSnapshot, NewsItem, StockAdvice, StockInfo

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"


def _get_api_key(cli_key: str | None = None) -> str | None:
    """获取 DeepSeek API Key：CLI 参数 > 环境变量 > 本地文件."""
    if cli_key:
        return cli_key
    env_key = os.environ.get("DEEPSEEK_API_KEY")
    if env_key:
        return env_key
    # 本地持久化文件
    key_file = Path(__file__).resolve().parent / ".deepseek_key"
    try:
        if key_file.exists():
            return key_file.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return None


def _build_prompt(
    stocks: list[StockInfo],
    snapshots: list[MarketSnapshot | None],
    theme: str | None,
) -> str:
    """构造发送给 DeepSeek 的 prompt."""

    # 行情数据段
    market_lines: list[str] = []
    for stock, snap in zip(stocks, snapshots):
        if snap and snap.price > 0:
            market_lines.append(
                f"- {snap.name} ({snap.symbol}) | 市场:{snap.market} "
                f"| 最新价:{snap.price} | 涨跌幅:{snap.change_pct:+.2f}% "
                f"| 昨收:{snap.prev_close} | 成交量:{snap.volume:,}"
            )
        else:
            market_lines.append(
                f"- {stock.input_symbol} ({stock.normalized_symbol}) | 行情数据获取失败"
            )

    market_text = "\n".join(market_lines) if market_lines else "无行情数据"
    theme_text = f"\n用户关注主题: {theme}" if theme else ""
    date_str = datetime.now().strftime("%Y-%m-%d")

    return f"""你是一个专业的股票分析师。根据以下今日({date_str})的真实行情数据，请完成分析任务。{theme_text}

## 当前持仓行情
{market_text}

## 分析要求

请严格按以下 JSON 格式返回（不要包含 markdown 代码块标记，只返回纯 JSON）：

{{
  "market_summary": "一句话总结整体市场表现（30字以内）",
  "news": [
    {{
      "title": "新闻标题（15-30字，模拟今日实际可能发生的与该股票相关的重大新闻）",
      "summary": "新闻摘要（50字以内）",
      "source": "信息来源（如 Reuters/Bloomberg/财联社 等）",
      "sentiment": "positive/negative/neutral",
      "affected_symbols": ["normalized_symbol_1"],
      "importance": "high/medium/low"
    }}
  ],
  "advice": [
    {{
      "symbol": "normalized_symbol",
      "action": "hold/watch/accumulate/reduce",
      "confidence": "high/medium/low",
      "reasons": ["理由1（20字以内）", "理由2（20字以内）"],
      "risk_note": "风险提示（可选，20字以内，没有则为空字符串）"
    }}
  ]
}}

## 重要规则
1. news 数组: 为每只股票生成 2-4 条最可能今日实际发生的相关新闻。新闻必须基于该股票的真实业务和行业动态（如财报、产品发布、政策变化、行业趋势等），不要编造虚构的公司名或产品名。
2. sentiment 判断: positive=利好(突破/增长/合作/超预期), negative=利空(制裁/限制/下跌/亏损/调查), neutral=中性
3. action 建议: 综合涨跌幅 + 消息面:
   - accumulate(加仓): 大涨+利好, 或大跌+利好(抄底)
   - reduce(减仓): 大跌+利空
   - watch(关注): 涨跌方向与消息面背离时
   - hold(持有): 小幅波动+消息中性
4. 每条 advice 的 reasons 必须具体引用行情数据（如"今日涨X%"）或新闻内容
5. affected_symbols 必须使用上面行情数据中的 normalized_symbol
6. 只返回 JSON，不要有任何额外文字

请开始分析:"""


def _call_deepseek(prompt: str, api_key: str, timeout: float = 30) -> dict[str, Any] | None:
    """调用 DeepSeek Chat API."""
    try:
        import requests
    except ImportError:
        logger.error("requests 未安装，无法调用 DeepSeek")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个专业的股票分析师。请只返回 JSON，不要有其他内容。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
    }

    try:
        resp = requests.post(DEEPSEEK_BASE_URL, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()

        # 去掉可能的 markdown 代码块标记
        if content.startswith("```"):
            content = content.split("\n", 1)[-1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            if content.startswith("json"):
                content = content[4:].strip()

        return json.loads(content)  # type: ignore[no-any-return]
    except json.JSONDecodeError as e:
        logger.error("DeepSeek 返回非 JSON: %s", str(e)[:200])
        return None
    except Exception as e:
        logger.error("DeepSeek API 调用失败: %s", e)
        return None


def analyze(
    stocks: list[StockInfo],
    snapshots: list[MarketSnapshot | None],
    theme: str | None = None,
    api_key: str | None = None,
) -> tuple[list[NewsItem], list[StockAdvice | None], str | None]:
    """使用 DeepSeek 一次性完成新闻分析 + 操作建议.

    Args:
        stocks: 股票列表
        snapshots: 行情快照（与stocks一一对应）
        theme: 关注主题
        api_key: DeepSeek API Key

    Returns:
        (news_items, advice_list, error_message)
        - 成功时 error_message 为 None
        - 失败时返回空列表和错误信息
    """
    key = _get_api_key(api_key)
    if not key:
        return [], [], "未设置 DEEPSEEK_API_KEY 环境变量或 --api-key 参数"

    prompt = _build_prompt(stocks, snapshots, theme)
    logger.info("调用 DeepSeek API...")
    result = _call_deepseek(prompt, key)

    if result is None:
        return [], [], "DeepSeek API 调用失败，请检查 API Key 和网络连接"

    # 解析 news
    news_items: list[NewsItem] = []
    for i, n in enumerate(result.get("news", [])):
        title = n.get("title", "")
        # URL：优先用 LLM 返回的，否则生成百度搜索链接
        url = n.get("url", "") or ""
        if not url and title:
            url = f"https://www.baidu.com/s?wd={urllib.parse.quote(title)}"
        news_items.append(NewsItem(
            title=title,
            summary=n.get("summary", ""),
            source=n.get("source", ""),
            url=url,
            published=datetime.now().strftime("%Y-%m-%d"),
            sentiment=n.get("sentiment", "neutral"),
            sentiment_score=0.0,  # LLM 直接给出分类
            affected_symbols=n.get("affected_symbols", []),
            relevance_score=0.8,
            importance=n.get("importance", "medium"),
            search_keyword="deepseek",
        ))

    # 解析 advice
    advice_list: list[StockAdvice | None] = []
    advice_map: dict[str, dict] = {}
    for a in result.get("advice", []):
        advice_map[a.get("symbol", "")] = a

    for stock, snap in zip(stocks, snapshots):
        if snap is None:
            advice_list.append(None)
            continue

        a = advice_map.get(stock.normalized_symbol, {})
        if not a:
            # LLM 没有返回该股票的建议，生成默认值
            advice_list.append(StockAdvice(
                symbol=stock.normalized_symbol,
                name=snap.name,
                action="hold",
                confidence="low",
                reasons=[f"{snap.name} 今日涨跌幅 {snap.change_pct:+.2f}%", "暂无具体分析"],
                price_change_pct=snap.change_pct,
                sentiment_bias="neutral",
                related_news_count=0,
            ))
            continue

        advice_list.append(StockAdvice(
            symbol=stock.normalized_symbol,
            name=snap.name,
            action=a.get("action", "hold"),
            confidence=a.get("confidence", "medium"),
            reasons=a.get("reasons", []),
            risk_note=a.get("risk_note") or None,
            price_change_pct=snap.change_pct,
            sentiment_bias="neutral",
            related_news_count=sum(
                1 for n in news_items
                if stock.normalized_symbol in n.affected_symbols
            ),
        ))

    logger.info(
        "DeepSeek 分析完成: %d 条新闻, %d 条建议",
        len(news_items), sum(1 for a in advice_list if a is not None),
    )
    return news_items, advice_list, None
