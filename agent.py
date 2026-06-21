"""ReAct Agent 核心 — 驱动 DeepSeek 自主决策、调用工具、生成分析报告.

模式: Think → Act → Observe → Think → ... → Submit Report

使用 DeepSeek 原生 function calling API，Agent 自主决定:
  - 何时获取行情数据
  - 从什么角度分析新闻
  - 是否需要深入挖掘某只股票
  - 何时信息足够，可以提交报告
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from models import (
    DailyBriefing, MarketSnapshot, NewsItem, StockAdvice, StockInfo, AgentState,
)
from llm import call_deepseek_agent
from tools import TOOL_DEFINITIONS, dispatch_tool

logger = logging.getLogger(__name__)

MAX_STEPS = 8  # 最多 8 轮工具调用


# ═══════════════════════════════════════════════════════════
# Agent 系统提示词
# ═══════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一个专业的股票分析 Agent。你有能力调用工具来获取实时数据、分析新闻和生成交易建议。

## 工作流程

请按照以下步骤完成分析任务：

0. **如果用户输入是自然语言（不是标准股票代码），先调用 parse_portfolio** — 将"我持有纳指科技ETF和SOXL"这类自然语言解析为标准股票代码
1. **调用 fetch_market_quotes** — 获取所有股票的实时行情数据（使用 parse_portfolio 返回的代码，或用户直接提供的代码）
2. **为每只股票调用 analyze_stock_news** — 根据涨跌幅和主题选择合适的分析角度：
   - 如果某只股票大涨/大跌（>2%），优先分析原因（"财报", "行业政策", "重大消息"）
   - 如果用户指定了主题，从该主题角度分析
   - 如果波动不大，分析"行业动态"或"技术面"
   - 对于特别重要的股票，可以从不同角度多次调用 analyze_stock_news
3. **为每只股票调用 generate_trading_advice** — 综合行情和新闻生成操作建议
4. **最后调用 submit_final_report** — 提交完整的分析报告

## 重要规则

- 判断用户输入是否为自然语言：如果包含"持仓"、"持有"、"买了"、"我的"等词或中文名称，先调用 parse_portfolio
- 每只股票都必须完成 行情获取 → 新闻分析 → 操作建议 三步
- 如果某只股票行情获取失败，跳过该股票的后续分析
- 新闻分析要基于股票的真实业务，不要编造
- 操作建议理由必须引用具体数据
- 完成所有分析后不要忘记调用 submit_final_report"""


# ═══════════════════════════════════════════════════════════
# Agent 循环
# ═══════════════════════════════════════════════════════════

def run_agent(
    raw_symbols: list[str],
    theme: str | None = None,
    api_key: str | None = None,
    verbose: bool = False,
) -> DailyBriefing:
    """运行 ReAct Agent 完成股票分析.

    Args:
        raw_symbols: 用户输入的股票代码列表
        theme: 关注主题（可选）
        api_key: DeepSeek API Key
        verbose: 是否输出详细日志

    Returns:
        包含完整分析结果的 DailyBriefing
    """
    state = AgentState()
    date_str = datetime.now().strftime("%Y-%m-%d")

    # 构建初始消息
    theme_hint = f"\n用户关注主题: {theme}" if theme else ""
    user_task = f"请分析以下股票代码: {', '.join(raw_symbols)}{theme_hint}\n当前日期: {date_str}"

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_task},
    ]

    logger.info("Agent 启动，目标股票: %s, 主题: %s", raw_symbols, theme or "无")

    # ── ReAct 循环 ──
    while state.step < MAX_STEPS:
        # Pre-flight: 检查步数
        state.step += 1
        logger.info("── Agent 第 %d/%d 步 ──", state.step, MAX_STEPS)

        # 调用 DeepSeek（带 tools）
        response = call_deepseek_agent(messages, tools=TOOL_DEFINITIONS, api_key=api_key)

        if response is None:
            logger.error("DeepSeek Agent API 第 %d 步调用失败", state.step)
            return _build_fallback_briefing(state, raw_symbols, date_str, "DeepSeek API 调用失败")

        content = response.get("content")
        tool_calls = response.get("tool_calls")

        # 情况1: 有工具调用 → 执行工具，结果反馈给 LLM
        if tool_calls:
            # 添加 assistant 消息（含 tool_calls）
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                }
                for tc in tool_calls
            ]
            messages.append(assistant_msg)

            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    tool_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    tool_args = {}
                    logger.warning("工具参数 JSON 解析失败: %s", tc["function"]["arguments"][:100])

                # 执行工具
                observation = dispatch_tool(tool_name, tool_args, state, api_key or "")
                state.observations.append(f"[{tool_name}]: {observation[:300]}")

                # 添加 tool 结果消息
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": observation,
                })

                # 检查是否是 submit_final_report
                if tool_name == "submit_final_report":
                    logger.info("Agent 提交最终报告，循环结束")
                    return _build_briefing_from_state(state, raw_symbols, date_str, theme)

            if verbose:
                print(f"  🔧 Step {state.step}: 调用了 {len(tool_calls)} 个工具 — "
                      f"{', '.join(tc['function']['name'] for tc in tool_calls)}")

        # 情况2: 只有文本内容，无工具调用 → Agent 可能想表达什么，继续循环
        elif content:
            messages.append({"role": "assistant", "content": content})
            logger.info("Agent 输出文本（无工具调用）: %s", content[:200])
            # 如果 Agent 连续两轮都不调用工具，可能是卡住了，给他一个提示
            messages.append({
                "role": "user",
                "content": "请继续分析。如果还没有获取行情数据，请调用 fetch_market_quotes。"
                           "如果已完成所有分析，请调用 submit_final_report 提交报告。",
            })

        # 情况3: 既无内容也无工具调用 → 异常
        else:
            logger.warning("Agent 第 %d 步返回空响应", state.step)
            messages.append({
                "role": "user",
                "content": "你的上一条响应为空。请根据当前进度继续分析，或调用 submit_final_report。",
            })

    # 达到最大步数 → 构建 fallback
    logger.warning("Agent 达到最大步数 %d，强制结束", MAX_STEPS)
    return _build_fallback_briefing(state, raw_symbols, date_str, "达到最大分析步数")


# ═══════════════════════════════════════════════════════════
# 简报构建
# ═══════════════════════════════════════════════════════════

def _build_briefing_from_state(
    state: AgentState,
    raw_symbols: list[str],
    date_str: str,
    theme: str | None = None,
) -> DailyBriefing:
    """从 Agent 累积状态构建 DailyBriefing（数据由工具直接写入 state）."""

    # ── 从 state.advice_data 构建 StockAdvice 列表 ──
    advice: list[StockAdvice | None] = []
    for stock, snap in zip(state.stocks, state.snapshots):
        if snap is None:
            advice.append(None)
            continue

        ad = state.advice_data.get(stock.normalized_symbol)
        if ad:
            # 统计该股票的相关新闻数
            related_count = sum(
                1 for n in state.news_items
                if stock.normalized_symbol in (n.affected_symbols or [])
            )
            advice.append(StockAdvice(
                symbol=stock.normalized_symbol,
                name=snap.name,
                action=ad.get("action", "hold"),
                confidence=ad.get("confidence", "medium"),
                reasons=ad.get("reasons", []),
                risk_note=ad.get("risk_note"),
                price_change_pct=snap.change_pct,
                sentiment_bias="neutral",
                related_news_count=related_count or len([
                    n for n in state.news_items
                    if stock.normalized_symbol in str(n.affected_symbols)
                ]),
            ))
        else:
            # 默认建议
            advice.append(StockAdvice(
                symbol=stock.normalized_symbol,
                name=snap.name,
                action="hold",
                confidence="low",
                reasons=[f"{snap.name} 今日涨跌幅 {snap.change_pct:+.2f}%", "Agent 未生成具体分析"],
                price_change_pct=snap.change_pct,
                sentiment_bias="neutral",
                related_news_count=0,
            ))

    # ── 数据状态 ──
    snapshots_clean = [s for s in state.snapshots if s is not None]
    data_status = "live"
    data_status_label = "🤖 Agent 分析 · 新浪财经"
    failed = sum(1 for s in state.snapshots if s is None)
    if failed > 0:
        data_status = "partial"
        data_status_label = f"🤖 Agent 分析 · 新浪财经（{failed}只失败）"
    if failed == len(state.snapshots) and len(state.snapshots) > 0:
        data_status = "error"
        data_status_label = "🤖 Agent 分析 · 行情获取失败"

    return DailyBriefing(
        date=date_str,
        disclaimer="⚠️ 本报告由 AI Agent 自主分析生成，仅供参考，不构成投资建议。投资有风险，决策需谨慎。",
        data_status=data_status,
        data_status_label=data_status_label,
        snapshots=snapshots_clean,
        news_items=state.news_items,
        advice=advice,
        dropped_news=[],
        errors=[],
        theme=theme,
    )


def _build_fallback_briefing(
    state: AgentState,
    raw_symbols: list[str],
    date_str: str,
    reason: str,
) -> DailyBriefing:
    """构建降级 DailyBriefing（Agent 失败时）."""
    return DailyBriefing(
        date=date_str,
        disclaimer="⚠️ 本报告由AI生成，仅供参考，不构成投资建议。",
        data_status="error",
        data_status_label=f"Agent 异常: {reason}",
        snapshots=[s for s in state.snapshots if s is not None],
        news_items=[],
        advice=[],
        errors=[reason],
    )
