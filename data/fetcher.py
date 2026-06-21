"""行情数据获取 — 新浪财经 API（A股/美股/港股），零依赖，真实数据.

API:
  A股: http://hq.sinajs.cn/list=sh600519 / sz000001
  美股: http://hq.sinajs.cn/list=gb_aapl
  港股: http://hq.sinajs.cn/list=hk00700
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from models import MarketSnapshot, StockInfo

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10  # 秒

MARKET_TIMEZONES: dict[str, str] = {
    "CN": "Asia/Shanghai",
    "US": "America/New_York",
    "HK": "Asia/Hong_Kong",
}

# ═══════════════════════════════════════════
# 符号转换: yfinance 格式 → 新浪格式
# ═══════════════════════════════════════════

def _to_sina_symbol(normalized: str, market: str) -> str:
    """yfinance 标准化代码 → 新浪代码."""
    if market == "CN":
        if normalized.endswith(".SS"):
            return f"sh{normalized.replace('.SS', '')}"
        elif normalized.endswith(".SZ"):
            return f"sz{normalized.replace('.SZ', '')}"
    elif market == "US":
        return f"gb_{normalized.lower()}"
    elif market == "HK":
        code = normalized.replace(".HK", "")
        # 港股需要5位数字补零: 700 → 00700, 9988 → 09988
        code = code.zfill(5)
        return f"hk{code}"
    return ""


# ═══════════════════════════════════════════
# 新浪通用获取
# ═══════════════════════════════════════════

def _fetch_sina(symbol: str, market: str, timeout: float = DEFAULT_TIMEOUT) -> MarketSnapshot | None:
    """从新浪获取单只股票行情（A股/美股/港股通用）."""
    sina_sym = _to_sina_symbol(symbol, market)
    if not sina_sym:
        return None

    url = f"http://hq.sinajs.cn/list={sina_sym}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "http://finance.sina.com.cn",
    }

    try:
        import requests
    except ImportError:
        logger.warning("requests 未安装")
        return None

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        # 新浪返回 GBK，先尝试 GBK，失败则 latin-1
        raw_bytes = resp.content
        try:
            text = raw_bytes.decode("gbk")
        except (UnicodeDecodeError, LookupError):
            text = raw_bytes.decode("latin-1")

        if not text.strip() or "FAILED" in text:
            return None

        # 解析 var hq_str_XXX="数据";
        match = re.search(r'"(.+)"', text)
        if not match:
            return None

        fields = match.group(1).split(",")
        if len(fields) < 4:
            return None

        if market == "US":
            return _parse_sina_us(symbol, fields)
        elif market == "HK":
            return _parse_sina_hk(symbol, fields)
        else:
            return _parse_sina_cn(symbol, fields)

    except Exception as e:
        logger.warning("新浪 %s 请求失败: %s", symbol, e)
        return None


def _parse_sina_cn(symbol: str, fields: list[str]) -> MarketSnapshot | None:
    """解析新浪 A 股数据.

    A股字段: 0:名称, 1:今开, 2:昨收, 3:现价, 4:最高, 5:最低,
             6:买入, 7:卖出, 8:成交量(手), 9:成交额,
             10-29:买卖五档, 30:日期, 31:时间
    """
    try:
        name = fields[0].strip() or symbol
        price = float(fields[3]) if fields[3] else 0.0
        prev_close = float(fields[2]) if fields[2] else 0.0
        if price <= 0:
            return None

        volume = int(float(fields[8]) * 100) if len(fields) > 8 and fields[8] else 0
        # 自己计算涨跌幅（新浪A股格式无直接涨跌幅字段）
        change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0.0
        change_amount = round(price - prev_close, 2)

        date_str = fields[30] if len(fields) > 30 and fields[30] else ""
        time_str = fields[31] if len(fields) > 31 and fields[31] else ""
        data_time = f"{date_str} {time_str}".strip() if date_str else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return MarketSnapshot(
            symbol=symbol, name=name, market="CN",
            price=round(price, 2), change_pct=change_pct,
            change_amount=change_amount, volume=volume,
            prev_close=round(prev_close, 2), data_time=data_time,
            market_status=_infer_market_status("CN"),
            timezone="Asia/Shanghai",
        )
    except (ValueError, IndexError) as e:
        logger.debug("解析A股 %s 失败: %s", symbol, e)
        return None


def _parse_sina_us(symbol: str, fields: list[str]) -> MarketSnapshot | None:
    """解析新浪美股数据.

    美股字段: 0:名称, 1:现价, 2:涨跌幅(%), 3:时间,
             4:涨跌额, 5:开盘, 6:最高, 7:最低,
             8:52周高, 9:52周低, 10:成交量
    """
    try:
        name = fields[0].strip() or symbol
        price = float(fields[1]) if fields[1] else 0.0
        change_pct = float(fields[2]) if fields[2] else 0.0
        data_time = fields[3] if len(fields) > 3 and fields[3] else ""
        change_amount = float(fields[4]) if len(fields) > 4 and fields[4] else 0.0
        volume = int(float(fields[10])) if len(fields) > 10 and fields[10] else 0
        prev_close = round(price - change_amount, 2) if change_amount != 0 else price

        if price <= 0:
            return None

        return MarketSnapshot(
            symbol=symbol, name=name, market="US",
            price=round(price, 2), change_pct=change_pct,
            change_amount=change_amount, volume=volume,
            prev_close=prev_close, data_time=data_time,
            market_status=_infer_market_status("US"),
            timezone="America/New_York",
        )
    except (ValueError, IndexError) as e:
        logger.debug("解析美股 %s 失败: %s", symbol, e)
        return None


def _parse_sina_hk(symbol: str, fields: list[str]) -> MarketSnapshot | None:
    """解析新浪港股数据.

    港股字段: 0:英文名, 1:中文名, 2:现价, 3:今开, 4:最高,
             5:最低, 6:昨收, 7:涨跌额, 8:涨跌幅(%),
             9:买入, 10:卖出, 11:成交额, 12:成交量, 17:日期, 18:时间
    """
    try:
        en_name = fields[0].strip() if fields[0] else ""
        cn_name = fields[1].strip() if len(fields) > 1 and fields[1] else ""
        name = cn_name or en_name or symbol

        price = float(fields[2]) if fields[2] else 0.0
        prev_close = float(fields[6]) if len(fields) > 6 and fields[6] else 0.0
        if price <= 0:
            return None

        change_pct = float(fields[8]) if len(fields) > 8 and fields[8] else 0.0
        change_amount = float(fields[7]) if len(fields) > 7 and fields[7] else 0.0
        volume = int(float(fields[12])) if len(fields) > 12 and fields[12] else 0

        date_str = fields[17] if len(fields) > 17 and fields[17] else ""
        time_str = fields[18] if len(fields) > 18 and fields[18] else ""
        data_time = f"{date_str} {time_str}".strip() if date_str else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return MarketSnapshot(
            symbol=symbol, name=name, market="HK",
            price=round(price, 2), change_pct=change_pct,
            change_amount=change_amount, volume=volume,
            prev_close=round(prev_close, 2), data_time=data_time,
            market_status=_infer_market_status("HK"),
            timezone="Asia/Hong_Kong",
        )
    except (ValueError, IndexError) as e:
        logger.debug("解析港股 %s 失败: %s", symbol, e)
        return None


# ═══════════════════════════════════════════
# 统一入口
# ═══════════════════════════════════════════

def fetch_one(
    normalized_symbol: str,
    name: str | None = None,
    market: str = "US",
    timeout: float = DEFAULT_TIMEOUT,
) -> MarketSnapshot | None:
    """获取单只股票行情 — 新浪财经（A股/美股/港股）.

    Returns:
        MarketSnapshot 或 None（获取失败）
    """
    return _fetch_sina(normalized_symbol, market, timeout)


def fetch_all(stocks: list[StockInfo], timeout: float = DEFAULT_TIMEOUT) -> list[MarketSnapshot | None]:
    """批量获取行情。返回与输入一一对应的列表，失败的为 None."""
    results: list[MarketSnapshot | None] = []
    for stock in stocks:
        snapshot = fetch_one(
            normalized_symbol=stock.normalized_symbol,
            name=stock.name,
            market=stock.market,
            timeout=timeout,
        )
        results.append(snapshot)
    return results


def all_failed(snapshots: list[MarketSnapshot | None]) -> bool:
    """检查是否所有行情获取都失败了."""
    if not snapshots:
        return True
    return all(s is None for s in snapshots)


def _infer_market_status(market: str) -> str:
    """推断市场状态."""
    now = datetime.now()
    hour = now.hour
    if market == "CN":
        if (9 <= hour < 11) or (hour == 11 and now.minute <= 30) or (13 <= hour < 15):
            return "盘中"
        return "已收盘"
    elif market == "US":
        if hour >= 22 or hour <= 4:
            return "盘中"
        return "已收盘"
    elif market == "HK":
        if (9 <= hour < 12) or (13 <= hour < 16):
            return "盘中"
        return "已收盘"
    return "未知"
