"""Agent 工具定义 & 实现 — ReAct Agent 可调用的 5 个工具.

工具:
  0. parse_portfolio       — 自然语言 → 股票代码
  1. fetch_market_quotes   — 解析代码 + 获取实时行情
  2. analyze_stock_news    — 搜索真实新闻 + DeepSeek 分析
  3. generate_trading_advice — DeepSeek 生成操作建议
  4. submit_final_report   — 提交最终报告，结束 Agent 循环
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import requests

from models import (
    MarketSnapshot, NewsItem, StockAdvice, StockInfo, AgentState,
)
from symbol_parser import parse_symbols
from data.fetcher import fetch_all as fetch_market_data
from llm import call_deepseek_tool

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# Tool Definitions (OpenAI/DeepSeek function-calling schema)
# ═══════════════════════════════════════════════════════════

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "parse_portfolio",
            "description": (
                "将用户的自然语言输入（如'我持有纳指科技ETF、中韩半导体ETF和美股SOXL'）"
                "解析为结构化的股票代码列表。当用户输入不是标准股票代码时，必须先调用此工具。"
                "能够识别：A股名称/代码、ETF名称、美股代码、港股名称/代码。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_text": {
                        "type": "string",
                        "description": "用户的自然语言输入，可能包含股票名称、ETF名称、代码等",
                    }
                },
                "required": ["user_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_market_quotes",
            "description": (
                "获取股票实时行情数据。传入用户输入的原始股票代码列表，"
                "返回解析后的股票信息和实时行情快照（价格、涨跌幅、成交量等）。"
                "在开始任何分析之前必须先调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "raw_symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "用户输入的原始股票代码列表，如 ['AAPL', '600519', '0700.HK']",
                    }
                },
                "required": ["raw_symbols"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_stock_news",
            "description": (
                "搜索并分析指定股票的真实新闻。从互联网搜索真实新闻文章，"
                "由 DeepSeek 进行情感分析（positive/negative/neutral）和重要性评估（high/medium/low）。"
                "可以多次调用以从不同角度深入分析同一只股票。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票标准化代码，如 'AAPL', '600519.SS', '0700.HK'",
                    },
                    "stock_name": {
                        "type": "string",
                        "description": "股票名称，如 '苹果', '贵州茅台'",
                    },
                    "market": {
                        "type": "string",
                        "enum": ["CN", "US", "HK"],
                        "description": "股票所属市场",
                    },
                    "focus": {
                        "type": "string",
                        "description": "分析角度，如 'AI业务进展', '财报业绩', '行业政策', '技术面', '竞争格局'",
                    },
                    "price_context": {
                        "type": "string",
                        "description": "当前行情数据（价格、涨跌幅等），用于生成贴合实际的新闻",
                    },
                },
                "required": ["symbol", "stock_name", "market", "focus"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_trading_advice",
            "description": (
                "基于已收集的行情数据和新闻分析，为指定股票生成操作建议。"
                "综合涨跌幅、消息面、市场情绪，给出持有/关注/加仓/减仓的建议及置信度。"
                "每只股票完成新闻分析后再调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票标准化代码",
                    },
                    "stock_name": {
                        "type": "string",
                        "description": "股票名称",
                    },
                    "findings_summary": {
                        "type": "string",
                        "description": "该股票的所有已收集信息摘要：行情数据、已分析的新闻、市场表现等",
                    },
                },
                "required": ["symbol", "stock_name", "findings_summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_final_report",
            "description": (
                "当所有股票都已完成行情获取、新闻分析和操作建议生成后，"
                "调用此工具提交最终报告。调用后分析任务完成。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "market_summary": {
                        "type": "string",
                        "description": "整体市场一句话总结（30字以内）",
                    },
                    "stocks_analyzed": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "symbol": {"type": "string"},
                                "name": {"type": "string"},
                                "action": {
                                    "type": "string",
                                    "enum": ["hold", "watch", "accumulate", "reduce"],
                                },
                                "confidence": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                },
                            },
                            "required": ["symbol", "name", "action", "confidence"],
                        },
                        "description": "已分析的股票列表及其最终建议",
                    },
                },
                "required": ["market_summary", "stocks_analyzed"],
            },
        },
    },
]


# ═══════════════════════════════════════════════════════════
# Real News Search
# ═══════════════════════════════════════════════════════════

def _search_real_news(query: str, timeout: float = 10) -> list[dict[str, str]]:
    """搜索真实新闻，返回 {title, url, source, snippet} 列表.

    依次尝试:
      1. Bing News RSS (全球覆盖，RSS 格式易解析)
      2. 百度新闻搜索 (国内覆盖好)
    """
    articles: list[dict[str, str]] = []

    # ── 源1: Bing News RSS ──
    try:
        bing_url = f"https://www.bing.com/news/search?q={urllib.parse.quote(query)}&format=rss&first=1"
        resp = requests.get(bing_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }, timeout=timeout)
        if resp.status_code == 200:
            root = ET.fromstring(resp.text)
            ns = {"ns": "http://www.w3.org/2005/Atom"}
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link = item.findtext("link", "").strip()
                source = item.findtext("source", "").strip()
                desc = item.findtext("description", "").strip()
                # 清理 HTML 标签
                desc = re.sub(r"<[^>]+>", "", desc)[:120]
                if title and link:
                    # 从 Bing apiclick 跳转链接中提取真实目标 URL
                    real_url = link
                    if "bing.com/news/apiclick" in link:
                        m = re.search(r'[?&]url=([^&]+)', link)
                        if m:
                            real_url = urllib.parse.unquote(m.group(1))
                    articles.append({
                        "title": title,
                        "url": real_url,
                        "source": source or "Bing News",
                        "snippet": desc,
                    })
    except Exception:
        pass

    # ── 源2: 百度新闻搜索 ──
    if len(articles) < 3:
        try:
            baidu_url = f"https://www.baidu.com/s?tn=news&rtt=1&bsst=1&wd={urllib.parse.quote(query)}"
            resp = requests.get(baidu_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html",
            }, timeout=timeout)
            if resp.status_code == 200:
                text = resp.text
                # 用正则从 HTML 中提取标题和链接
                # 百度新闻结果格式: <h3 class="news-title_1YtI1"><a href="URL" ...>标题</a>
                pattern = r'<a\s+[^>]*href\s*=\s*"([^"]+)"[^>]*>(.+?)</a>'
                matches = re.findall(pattern, text)
                seen_urls = {a["url"] for a in articles}
                for url, title in matches:
                    title = re.sub(r"<[^>]+>", "", title).strip()
                    if title and url.startswith("http") and url not in seen_urls and len(title) > 8:
                        articles.append({
                            "title": title,
                            "url": url,
                            "source": "百度新闻",
                            "snippet": "",
                        })
                        seen_urls.add(url)
        except Exception:
            pass

    # 返回前8条
    return articles[:8]


# ═══════════════════════════════════════════════════════════
# Tool Implementations
# ═══════════════════════════════════════════════════════════

def _tool_parse_portfolio(user_text: str, api_key: str = "", state: AgentState | None = None) -> str:
    """执行 parse_portfolio 工具 — 用 DeepSeek 从自然语言中提取股票代码."""
    prompt = f"""你是一个股票代码识别专家。请从以下用户输入中提取所有提到的股票/ETF，并给出标准代码。

用户输入: {user_text}

已知的常见 ETF 和股票映射（优先使用）:
- 纳指科技ETF / 纳斯达克科技ETF → 513100.SS (A股)
- 中韩半导体ETF → 513310.SS (A股)
- 纳指ETF / 纳斯达克ETF → 513100.SS 或 159941.SZ
- 芯片ETF → 159995.SZ
- 半导体ETF → 512480.SS
- 白酒ETF / 酒ETF → 512690.SS
- 新能源ETF → 516160.SS
- 医药ETF → 512010.SS
- 恒生科技ETF → 513180.SS
- 沪深300ETF → 510300.SS
- 科创50ETF → 588000.SS
- SOXL → SOXL (美股，三倍做多半导体ETF)
- TQQQ → TQQQ (美股，三倍做多纳指ETF)
- SQQQ → SQQQ (美股，三倍做空纳指ETF)

对于未在上述列表中的名称，请根据你的知识推断最可能的股票代码。

请严格按以下 JSON 格式返回（不要包含 markdown 代码块标记）:

{{
  "stocks": [
    {{
      "name": "股票/ETF名称（中文或英文）",
      "code": "标准代码（如 513100.SS, AAPL, 0700.HK, SOXL）",
      "market": "CN/US/HK",
      "confidence": "high/medium/low"
    }}
  ],
  "unrecognized": ["无法识别的名称列表"]
}}

规则:
1. 每个股票/ETF 都必须有 code 和 market
2. A股 ETF 代码以 .SS 或 .SZ 结尾
3. 美股代码保持原样（纯字母）
4. 港股代码以 .HK 结尾（4位数字）
5. 只返回 JSON，不要有任何额外文字"""

    result = call_deepseek_tool(prompt, api_key)
    if result is None:
        return json.dumps({"error": "DeepSeek 调用失败，无法解析持仓"}, ensure_ascii=False)

    # 提取 raw_symbols 并写入 state
    raw_symbols = [s.get("code", "") for s in result.get("stocks", []) if s.get("code")]
    if state is not None and raw_symbols:
        # 暂存到 observations 供后续使用
        state.observations.append(f"[parse_portfolio]: 识别到 {len(raw_symbols)} 只标的: {', '.join(raw_symbols)}")

    result["raw_symbols"] = raw_symbols
    return json.dumps(result, ensure_ascii=False)


def _tool_fetch_market_quotes(raw_symbols: list[str], state: AgentState) -> str:
    """执行 fetch_market_quotes 工具."""
    stocks, errors = parse_symbols(raw_symbols)
    if not stocks:
        return json.dumps({"error": "无法解析任何股票代码", "details": errors}, ensure_ascii=False)

    snapshots = fetch_market_data(stocks)
    state.stocks = stocks
    state.snapshots = snapshots

    # 构建返回结果
    results: list[dict] = []
    for stock, snap in zip(stocks, snapshots):
        if snap and snap.price > 0:
            results.append({
                "symbol": stock.normalized_symbol,
                "name": snap.name,
                "market": stock.market,
                "price": snap.price,
                "change_pct": snap.change_pct,
                "change_amount": snap.change_amount,
                "volume": snap.volume,
                "prev_close": snap.prev_close,
                "market_status": snap.market_status,
            })
        else:
            results.append({
                "symbol": stock.normalized_symbol,
                "name": stock.input_symbol,
                "market": stock.market,
                "error": "行情获取失败",
            })

    summary = {
        "total": len(results),
        "success": sum(1 for r in results if "error" not in r),
        "failed": sum(1 for r in results if "error" in r),
        "parse_errors": errors,
        "stocks": results,
    }
    return json.dumps(summary, ensure_ascii=False)


def _tool_analyze_stock_news(
    symbol: str,
    stock_name: str,
    market: str,
    focus: str,
    price_context: str = "",
    api_key: str = "",
    state: AgentState | None = None,
) -> str:
    """执行 analyze_stock_news 工具 — 搜索真实新闻 + DeepSeek 分析情感."""
    market_labels = {"CN": "A股", "US": "美股", "HK": "港股"}
    market_label = market_labels.get(market, market)
    date_str = datetime.now().strftime("%Y-%m-%d")

    # ── Step 1: 搜索真实新闻 ──
    search_query = f"{stock_name} {focus}" if focus else stock_name
    # 中概股用中文名搜索
    if market == "CN":
        search_query = f"{stock_name} {focus}"
    elif market == "HK":
        search_query = f"{stock_name} 港股 {focus}"

    logger.info("搜索真实新闻: %s", search_query)
    real_articles = _search_real_news(search_query)

    # ── Step 2: DeepSeek 分析真实新闻 ──
    if real_articles:
        articles_text = "\n".join(
            f"{i+1}. [{a['source']}] {a['title']}\n   URL: {a['url']}\n   摘要: {a.get('snippet', '')[:100]}"
            for i, a in enumerate(real_articles)
        )
        prompt = f"""你是一个专业的股票分析师。以下是关于 {stock_name} ({symbol}, {market_label}) 的真实新闻列表。

股票信息:
- 名称: {stock_name}
- 代码: {symbol}
- 市场: {market_label}
{price_context}

分析角度: {focus}

真实新闻列表:
{articles_text}

请从以上新闻中选出 2-4 条最相关、最重要的，进行情感分析和总结。严格按以下 JSON 格式返回（不要包含 markdown 代码块标记）:

{{
  "news": [
    {{
      "title": "使用原始新闻标题",
      "url": "原始新闻URL",
      "summary": "基于该新闻内容的分析摘要（50字以内）",
      "source": "新闻来源",
      "sentiment": "positive/negative/neutral",
      "importance": "high/medium/low"
    }}
  ]
}}

规则:
1. title 和 url 必须使用上面真实新闻列表中的原始值
2. sentiment: positive=利好, negative=利空, neutral=中性
3. importance: high=对股价影响大, medium=一般影响, low=影响微小
4. 按重要度和相关性排序，最多选4条
5. 只返回 JSON，不要有任何额外文字"""
    else:
        # 无搜索结果时，由 DeepSeek 生成新闻（降级）
        logger.info("无搜索结果，由 DeepSeek 生成新闻")
        prompt = f"""你是一个专业的股票分析师。请根据以下信息，为 {stock_name} ({symbol}) 生成 2-3 条今日({date_str})最可能发生的真实相关新闻。

股票信息:
- 名称: {stock_name}
- 代码: {symbol}
- 市场: {market_label}
{price_context}

分析角度: {focus}

请严格按以下 JSON 格式返回（不要包含 markdown 代码块标记）:

{{
  "news": [
    {{
      "title": "新闻标题（15-30字，基于真实业务和行业动态）",
      "summary": "新闻摘要（50字以内）",
      "source": "信息来源（如 Reuters/Bloomberg/财联社/证券时报 等）",
      "sentiment": "positive/negative/neutral",
      "importance": "high/medium/low"
    }}
  ]
}}

规则:
1. 新闻必须与该股票的真实业务和行业动态相关
2. 情感判断: positive=利好, negative=利空, neutral=中性
3. 重要度: high=对股价影响大, medium=一般影响, low=影响微小
4. 只返回 JSON，不要有任何额外文字"""

    result = call_deepseek_tool(prompt, api_key)
    if result is None:
        return json.dumps({"error": "DeepSeek 调用失败，无法生成新闻"}, ensure_ascii=False)

    # ── Step 3: 写入 state，使用真实 URL ──
    for n in result.get("news", []):
        title = n.get("title", "")
        url = n.get("url", "")
        # 只有当没有真实 URL 时才生成百度搜索链接
        if not url and title:
            url = f"https://www.baidu.com/s?wd={urllib.parse.quote(title)}"

        if state is not None:
            state.news_items.append(NewsItem(
                title=title,
                summary=n.get("summary", ""),
                source=n.get("source", ""),
                url=url,
                published=date_str,
                sentiment=n.get("sentiment", "neutral"),
                sentiment_score=0.0,
                affected_symbols=[symbol],
                relevance_score=0.8,
                importance=n.get("importance", "medium"),
                search_keyword=f"agent:{focus}",
            ))

        n["url"] = url

    news_count = len(result.get("news", []))
    logger.info("analyze_stock_news: %d 条新闻 (%d 条真实搜索)", news_count, len(real_articles))
    return json.dumps(result, ensure_ascii=False)


def _tool_generate_trading_advice(
    symbol: str,
    stock_name: str,
    findings_summary: str,
    api_key: str = "",
    state: AgentState | None = None,
) -> str:
    """执行 generate_trading_advice 工具 — 调用 DeepSeek 生成建议并写入 state."""
    date_str = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""你是一个专业的股票分析师。请根据以下已收集的信息，为 {stock_name} ({symbol}) 生成今日({date_str})操作建议。

已收集信息:
{findings_summary}

请严格按以下 JSON 格式返回（不要包含 markdown 代码块标记）:

{{
  "action": "hold/watch/accumulate/reduce",
  "confidence": "high/medium/low",
  "reasons": ["理由1（20字以内，必须引用具体数据）", "理由2（20字以内）", "理由3（可选）"],
  "risk_note": "风险提示（20字以内，没有则为空字符串）"
}}

规则:
1. action: accumulate(加仓)=大涨+利好或大跌+利好(抄底), reduce(减仓)=大跌+利空, watch(关注)=涨跌与消息背离, hold(持有)=小波动+中性
2. reasons 必须引用具体行情数据（如"今日涨X%"）或新闻内容
3. 只返回 JSON，不要有任何额外文字"""

    result = call_deepseek_tool(prompt, api_key)
    if result is None:
        return json.dumps({"error": "DeepSeek 调用失败，无法生成建议"}, ensure_ascii=False)

    # 写入 state
    if state is not None:
        state.advice_data[symbol] = {
            "action": result.get("action", "hold"),
            "confidence": result.get("confidence", "medium"),
            "reasons": result.get("reasons", []),
            "risk_note": result.get("risk_note") or None,
        }

    return json.dumps(result, ensure_ascii=False)


def _tool_submit_final_report(
    market_summary: str,
    stocks_analyzed: list[dict],
    state: AgentState,
) -> str:
    """执行 submit_final_report 工具 — 标记 Agent 完成."""
    state.observations.append(f"最终报告: {market_summary}")
    state.submitted = True
    return json.dumps({
        "status": "accepted",
        "message": "报告已提交，分析完成。",
        "stocks_count": len(stocks_analyzed),
    }, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# Tool Dispatch
# ═══════════════════════════════════════════════════════════

def dispatch_tool(
    tool_name: str,
    tool_args: dict[str, Any],
    state: AgentState,
    api_key: str = "",
) -> str:
    """执行工具调用并返回结果字符串.

    Args:
        tool_name: 工具名称
        tool_args: LLM 传入的参数
        state: Agent 状态（会原地更新）
        api_key: DeepSeek API Key

    Returns:
        工具执行结果（JSON 字符串）
    """
    logger.info("Agent 调用工具: %s(%s)", tool_name, tool_args)

    try:
        if tool_name == "parse_portfolio":
            result = _tool_parse_portfolio(
                user_text=tool_args.get("user_text", ""),
                api_key=api_key,
                state=state,
            )
        elif tool_name == "fetch_market_quotes":
            result = _tool_fetch_market_quotes(
                tool_args.get("raw_symbols", []), state
            )
        elif tool_name == "analyze_stock_news":
            result = _tool_analyze_stock_news(
                symbol=tool_args.get("symbol", ""),
                stock_name=tool_args.get("stock_name", ""),
                market=tool_args.get("market", ""),
                focus=tool_args.get("focus", ""),
                price_context=tool_args.get("price_context", ""),
                api_key=api_key,
                state=state,
            )
        elif tool_name == "generate_trading_advice":
            result = _tool_generate_trading_advice(
                symbol=tool_args.get("symbol", ""),
                stock_name=tool_args.get("stock_name", ""),
                findings_summary=tool_args.get("findings_summary", ""),
                api_key=api_key,
                state=state,
            )
        elif tool_name == "submit_final_report":
            result = _tool_submit_final_report(
                market_summary=tool_args.get("market_summary", ""),
                stocks_analyzed=tool_args.get("stocks_analyzed", []),
                state=state,
            )
        else:
            result = json.dumps({"error": f"未知工具: {tool_name}"})

        state.tool_log.append({
            "step": state.step,
            "tool": tool_name,
            "args": tool_args,
            "result_summary": result[:200] + ("..." if len(result) > 200 else ""),
        })
        return result

    except Exception as e:
        logger.exception("工具 %s 执行异常", tool_name)
        return json.dumps({"error": f"工具执行失败: {str(e)}"}, ensure_ascii=False)
