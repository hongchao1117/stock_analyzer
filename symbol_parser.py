"""股票代码解析器 — 识别市场、标准化代码格式（新浪财经兼容）.

支持格式:
  A股: 600519, 000001, 300750, 688981 (纯6位数字)
      600519.SH, 300750.SZ (带后缀)
  美股: AAPL, NVDA, TSLA (纯字母1-5位)
  港股: 0700, 00700, 9988 (4-5位数字), 0700.HK (带后缀)
"""

from __future__ import annotations

import re
import logging

from models import StockInfo

logger = logging.getLogger(__name__)


class SymbolParseError(ValueError):
    """股票代码无法识别时抛出."""


# ---- 识别规则 ----

# 港股: 4-5位数字（但非6位A股格式）
_HK_DIGIT_ONLY = re.compile(r"^\d{4,5}$")

# A股: 6位数字
_A_SHARE_DIGIT_ONLY = re.compile(r"^\d{6}$")

# 美股: 纯字母 1-5 位
_US_LETTERS = re.compile(r"^[A-Za-z]{1,5}$")

# 已带后缀
_SUFFIXED = re.compile(r"^(.+)\.(HK|SS|SZ|SH)$", re.IGNORECASE)


def parse_symbol(raw: str) -> StockInfo:
    """解析单个股票代码.

    Args:
        raw: 用户输入的原始代码

    Returns:
        StockInfo，包含市场分类和标准化代码

    Raises:
        SymbolParseError: 代码格式无法识别
    """
    raw = raw.strip().upper()

    if not raw:
        raise SymbolParseError("空字符串不是有效的股票代码")

    # ---- 带后缀的先处理 ----
    m = _SUFFIXED.match(raw)
    if m:
        code = m.group(1)
        suffix = m.group(2).upper()

        if suffix == "HK":
            code_padded = code.zfill(4)  # 港股补零到4位
            return StockInfo(
                input_symbol=raw,
                normalized_symbol=f"{code_padded}.HK",
                market="HK",
            )
        elif suffix in ("SS", "SH"):
            # .SH → 统一转为 .SS (新浪/标准格式)
            return StockInfo(
                input_symbol=raw,
                normalized_symbol=f"{code}.SS",
                market="CN",
            )
        elif suffix == "SZ":
            return StockInfo(
                input_symbol=raw,
                normalized_symbol=f"{code}.SZ",
                market="CN",
            )

    # ---- 纯数字 ----
    if raw.isdigit():
        # A股: 6位数字
        if _A_SHARE_DIGIT_ONLY.match(raw):
            prefix = raw[:2]
            if prefix in ("60", "51", "68"):
                # 上交所: 60xxxx (主板), 51xxxx (ETF), 68xxxx (科创板)
                return StockInfo(
                    input_symbol=raw,
                    normalized_symbol=f"{raw}.SS",
                    market="CN",
                )
            elif prefix in ("00", "30"):
                # 深交所: 00xxxx (主板), 30xxxx (创业板)
                return StockInfo(
                    input_symbol=raw,
                    normalized_symbol=f"{raw}.SZ",
                    market="CN",
                )
            else:
                raise SymbolParseError(
                    f"无法识别的A股代码: {raw}（6位代码应以 60/51/68/00/30 开头）"
                )

        # 港股: 4-5位数字
        if _HK_DIGIT_ONLY.match(raw):
            code_padded = raw.zfill(4)  # 统一补零到4位，如 700 → 0700
            return StockInfo(
                input_symbol=raw,
                normalized_symbol=f"{code_padded}.HK",
                market="HK",
            )

        # 其他纯数字无法识别
        raise SymbolParseError(
            f"无法识别的数字代码: {raw}（A股为6位，港股为4-5位）"
        )

    # ---- 纯字母（美股） ----
    if _US_LETTERS.match(raw):
        return StockInfo(
            input_symbol=raw,
            normalized_symbol=raw,
            market="US",
        )

    # ---- 兜底 ----
    raise SymbolParseError(
        f"无法识别的股票代码格式: {raw}。"
        f"支持: A股6位数字、美股字母代码、港股4-5位数字、或带后缀如0700.HK"
    )


def parse_symbols(raw_list: list[str]) -> tuple[list[StockInfo], list[str]]:
    """批量解析股票代码，无效代码跳过并记录错误.

    Args:
        raw_list: 用户输入的原始代码列表

    Returns:
        (成功解析的 StockInfo 列表, 错误信息列表)
    """
    stocks: list[StockInfo] = []
    errors: list[str] = []

    for raw in raw_list:
        raw = raw.strip()
        if not raw:
            continue  # 跳过空字符串
        try:
            stock = parse_symbol(raw)
            # 检查重复
            if any(s.normalized_symbol == stock.normalized_symbol for s in stocks):
                errors.append(f"重复代码已跳过: {stock.input_symbol}")
                continue
            stocks.append(stock)
        except SymbolParseError as e:
            errors.append(str(e))
            logger.warning("跳过无效代码 %s: %s", raw, e)

    return stocks, errors
