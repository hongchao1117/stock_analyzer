"""Mock 数据 — 网络不可用或 --mock 模式时的兜底数据.

覆盖三个市场（A股/美股/港股），包含行情和新闻。
每个被 mock 的 symbol 需要有对应的 MarketSnapshot 和关键词。
"""

from __future__ import annotations

from models import MarketSnapshot


# ---- Mock 股票名称映射 ----
# normalized_symbol → 显示名称
MOCK_NAMES: dict[str, str] = {
    "513100.SS": "纳指科技ETF",
    "513310.SS": "中韩半导体ETF",
    "600519.SS": "贵州茅台",
    "000001.SZ": "平安银行",
    "300750.SZ": "宁德时代",
    "688981.SS": "中芯国际",
    "AAPL": "Apple Inc.",
    "NVDA": "NVIDIA Corp.",
    "TSLA": "Tesla Inc.",
    "MSFT": "Microsoft Corp.",
    "0700.HK": "腾讯控股",
    "9988.HK": "阿里巴巴-SW",
    "0941.HK": "中国移动",
}

# normalized_symbol → 相关关键词（用于新闻→标的映射）
MOCK_KEYWORDS: dict[str, list[str]] = {
    "513100.SS": [
        "纳指科技", "纳斯达克", "NASDAQ", "NVIDIA", "英伟达",
        "AI芯片", "GPU", "大模型", "OpenAI", "Microsoft", "Google",
        "Apple", "Meta", "Broadcom", "算力", "人工智能",
    ],
    "513310.SS": [
        "中韩半导体", "半导体", "芯片", "三星", "SK海力士",
        "中芯国际", "存储芯片", "HBM", "光刻", "ASML",
        "晶圆", "封装", "台积电", "TSMC",
    ],
    "600519.SS": [
        "茅台", "白酒", "消费", "食品饮料", "贵州茅台",
    ],
    "000001.SZ": [
        "平安银行", "银行", "金融",
    ],
    "300750.SZ": [
        "宁德时代", "新能源", "电池", "锂电", "储能", "CATL",
    ],
    "688981.SS": [
        "中芯国际", "芯片", "晶圆", "半导体", "SMIC",
    ],
    "AAPL": [
        "Apple", "苹果", "iPhone", "iOS", "App Store",
    ],
    "NVDA": [
        "NVIDIA", "英伟达", "GPU", "AI芯片", "CUDA", "数据中心",
    ],
    "TSLA": [
        "Tesla", "特斯拉", "电动车", "FSD", "自动驾驶",
    ],
    "MSFT": [
        "Microsoft", "微软", "Azure", "OpenAI", "Office",
    ],
    "0700.HK": [
        "腾讯", "微信", "游戏", "Tencent", "云计算",
    ],
    "9988.HK": [
        "阿里巴巴", "阿里", "淘宝", "天猫", "Alibaba", "电商",
    ],
    "0941.HK": [
        "中国移动", "移动", "5G", "运营商",
    ],
}

# normalized_symbol → 所属市场
MOCK_MARKETS: dict[str, str] = {
    "513100.SS": "CN", "513310.SS": "CN", "600519.SS": "CN",
    "000001.SZ": "CN", "300750.SZ": "CN", "688981.SS": "CN",
    "AAPL": "US", "NVDA": "US", "TSLA": "US", "MSFT": "US",
    "0700.HK": "HK", "9988.HK": "HK", "0941.HK": "HK",
}


def get_mock_name(normalized_symbol: str) -> str:
    """获取 mock 股票名称."""
    return MOCK_NAMES.get(normalized_symbol, normalized_symbol)


def get_mock_keywords(normalized_symbol: str) -> list[str]:
    """获取 mock 股票的相关关键词."""
    return MOCK_KEYWORDS.get(normalized_symbol, [])


def get_mock_market(normalized_symbol: str) -> str:
    """获取 mock 股票市场."""
    return MOCK_MARKETS.get(normalized_symbol, "US")


def get_mock_snapshot(normalized_symbol: str) -> MarketSnapshot | None:
    """获取单只股票的 mock 行情快照.

    Args:
        normalized_symbol: yfinance 标准化代码

    Returns:
        MarketSnapshot 或 None（未知代码）
    """
    name = get_mock_name(normalized_symbol)
    market = get_mock_market(normalized_symbol)

    # 预置 mock 行情数据
    snapshots: dict[str, MarketSnapshot] = {
        "513100.SS": MarketSnapshot(
            symbol="513100.SS", name="纳指科技ETF", market="CN",
            price=1.856, change_pct=-1.20, change_amount=-0.023,
            volume=120_000_000, prev_close=1.879,
            data_time="2026-06-21 15:00:00 CST",
            market_status="已收盘", timezone="Asia/Shanghai",
        ),
        "513310.SS": MarketSnapshot(
            symbol="513310.SS", name="中韩半导体ETF", market="CN",
            price=1.234, change_pct=-0.80, change_amount=-0.010,
            volume=80_000_000, prev_close=1.244,
            data_time="2026-06-21 15:00:00 CST",
            market_status="已收盘", timezone="Asia/Shanghai",
        ),
        "600519.SS": MarketSnapshot(
            symbol="600519.SS", name="贵州茅台", market="CN",
            price=1680.00, change_pct=1.50, change_amount=24.85,
            volume=3_500_000, prev_close=1655.15,
            data_time="2026-06-21 15:00:00 CST",
            market_status="已收盘", timezone="Asia/Shanghai",
        ),
        "000001.SZ": MarketSnapshot(
            symbol="000001.SZ", name="平安银行", market="CN",
            price=12.35, change_pct=-0.40, change_amount=-0.05,
            volume=45_000_000, prev_close=12.40,
            data_time="2026-06-21 15:00:00 CST",
            market_status="已收盘", timezone="Asia/Shanghai",
        ),
        "300750.SZ": MarketSnapshot(
            symbol="300750.SZ", name="宁德时代", market="CN",
            price=210.50, change_pct=2.80, change_amount=5.73,
            volume=18_000_000, prev_close=204.77,
            data_time="2026-06-21 15:00:00 CST",
            market_status="已收盘", timezone="Asia/Shanghai",
        ),
        "688981.SS": MarketSnapshot(
            symbol="688981.SS", name="中芯国际", market="CN",
            price=52.30, change_pct=-1.80, change_amount=-0.96,
            volume=22_000_000, prev_close=53.26,
            data_time="2026-06-21 15:00:00 CST",
            market_status="已收盘", timezone="Asia/Shanghai",
        ),
        "AAPL": MarketSnapshot(
            symbol="AAPL", name="Apple Inc.", market="US",
            price=198.75, change_pct=0.85, change_amount=1.67,
            volume=55_000_000, prev_close=197.08,
            data_time="2026-06-20 16:00:00 EST",
            market_status="已收盘", timezone="America/New_York",
        ),
        "NVDA": MarketSnapshot(
            symbol="NVDA", name="NVIDIA Corp.", market="US",
            price=142.30, change_pct=4.20, change_amount=5.73,
            volume=78_000_000, prev_close=136.57,
            data_time="2026-06-20 16:00:00 EST",
            market_status="已收盘", timezone="America/New_York",
        ),
        "TSLA": MarketSnapshot(
            symbol="TSLA", name="Tesla Inc.", market="US",
            price=248.50, change_pct=-2.30, change_amount=-5.85,
            volume=95_000_000, prev_close=254.35,
            data_time="2026-06-20 16:00:00 EST",
            market_status="已收盘", timezone="America/New_York",
        ),
        "MSFT": MarketSnapshot(
            symbol="MSFT", name="Microsoft Corp.", market="US",
            price=465.20, change_pct=0.55, change_amount=2.54,
            volume=22_000_000, prev_close=462.66,
            data_time="2026-06-20 16:00:00 EST",
            market_status="已收盘", timezone="America/New_York",
        ),
        "0700.HK": MarketSnapshot(
            symbol="0700.HK", name="腾讯控股", market="HK",
            price=385.00, change_pct=1.20, change_amount=4.56,
            volume=18_000_000, prev_close=380.44,
            data_time="2026-06-21 16:08:00 HKT",
            market_status="已收盘", timezone="Asia/Hong_Kong",
        ),
        "9988.HK": MarketSnapshot(
            symbol="9988.HK", name="阿里巴巴-SW", market="HK",
            price=78.50, change_pct=-1.50, change_amount=-1.20,
            volume=35_000_000, prev_close=79.70,
            data_time="2026-06-21 16:08:00 HKT",
            market_status="已收盘", timezone="Asia/Hong_Kong",
        ),
        "0941.HK": MarketSnapshot(
            symbol="0941.HK", name="中国移动", market="HK",
            price=72.80, change_pct=0.55, change_amount=0.40,
            volume=12_000_000, prev_close=72.40,
            data_time="2026-06-21 16:08:00 HKT",
            market_status="已收盘", timezone="Asia/Hong_Kong",
        ),
    }

    result = snapshots.get(normalized_symbol)
    if result is None:
        # 未知代码 → 返回一个通用的 mock 快照
        result = MarketSnapshot(
            symbol=normalized_symbol, name=name, market=market,
            price=100.00, change_pct=0.00, change_amount=0.00,
            volume=10_000_000, prev_close=100.00,
            data_time="2026-06-21 15:00:00",
            market_status="已收盘",
            timezone="Asia/Shanghai" if market == "CN"
            else "America/New_York" if market == "US"
            else "Asia/Hong_Kong",
        )
    return result


def get_mock_snapshots(normalized_symbols: list[str]) -> list[MarketSnapshot | None]:
    """批量获取 mock 行情，保持与输入顺序一致."""
    return [get_mock_snapshot(s) for s in normalized_symbols]


# ---- Mock 新闻数据 ----

MOCK_NEWS: list[dict] = [
    # ---- AI产业链 / 纳指科技ETF 相关 ----
    {
        "title": "NVIDIA发布新一代AI芯片B200，性能提升4倍",
        "summary": "NVIDIA在GTC大会上正式发布Blackwell B200 GPU，AI训练性能较上一代Hopper架构提升4倍，预计Q3量产交付。",
        "source": "Reuters",
        "url": "https://example.com/nvidia-b200",
        "published": "2026-06-21",
        "search_keyword": "NVIDIA",
    },
    {
        "title": "微软宣布追加500亿美元AI基础设施投资",
        "summary": "微软计划在2026-2027年追加500亿美元用于AI数据中心建设，扩大与OpenAI的合作，利好AI算力产业链。",
        "source": "Bloomberg",
        "url": "https://example.com/msft-ai-investment",
        "published": "2026-06-21",
        "search_keyword": "AI芯片",
    },
    {
        "title": "台积电3nm产能满载，AI芯片订单排至2027年",
        "summary": "台积电表示3nm和先进封装产能持续供不应求，来自NVIDIA、AMD等AI芯片订单已排至2027年上半年。",
        "source": "Digitimes",
        "url": "https://example.com/tsmc-3nm",
        "published": "2026-06-21",
        "search_keyword": "AI芯片",
    },
    {
        "title": "纳斯达克100指数再创新高，科技股领涨",
        "summary": "受AI产业景气度持续推动，纳斯达克100指数周五收涨1.8%，创历史新高。NVIDIA、微软等AI概念股领涨。",
        "source": "WSJ",
        "url": "https://example.com/nasdaq-record",
        "published": "2026-06-20",
        "search_keyword": "纳斯达克",
    },
    {
        "title": "苹果计划在iPhone 18中集成更强大的端侧AI能力",
        "summary": "Apple正与多家AI芯片供应商洽谈，计划在下一代iPhone中大幅提升端侧AI推理能力，利好AI芯片需求。",
        "source": "Bloomberg",
        "url": "https://example.com/apple-ai-iphone",
        "published": "2026-06-20",
        "search_keyword": "AI",
    },

    # ---- 半导体 / 中韩半导体ETF 相关 ----
    {
        "title": "韩国拟扩大对华芯片设备出口审查范围",
        "summary": "韩国政府计划将更多半导体设备列入对华出口审查清单，可能影响三星、SK海力士等企业在华业务。",
        "source": "Yonhap",
        "url": "https://example.com/korea-chip-export",
        "published": "2026-06-21",
        "search_keyword": "半导体",
    },
    {
        "title": "SK海力士HBM3E订单已排至2027年，供不应求",
        "summary": "SK海力士宣布其HBM3E高带宽内存订单已满，产能无法满足NVIDIA等客户需求，正考虑进一步扩产。",
        "source": "Reuters",
        "url": "https://example.com/skhynix-hbm",
        "published": "2026-06-21",
        "search_keyword": "SK海力士",
    },
    {
        "title": "中芯国际28nm产能利用率回升至85%",
        "summary": "中芯国际Q2财报显示28nm及以上成熟制程产能利用率显著回升，受益于国产替代加速和消费电子回暖。",
        "source": "财联社",
        "url": "https://example.com/smic-28nm",
        "published": "2026-06-20",
        "search_keyword": "中芯国际",
    },
    {
        "title": "美国或进一步限制对华先进芯片制造设备出口",
        "summary": "据知情人士透露，美国政府正考虑扩大对华半导体设备出口限制，可能涉及更多ASML和应材设备型号。",
        "source": "Reuters",
        "url": "https://example.com/us-chip-ban",
        "published": "2026-06-20",
        "search_keyword": "芯片",
    },
    {
        "title": "半导体行业景气度持续回升，费城半导体指数连涨5周",
        "summary": "受益于AI和存储芯片需求旺盛，费城半导体指数连续5周上涨，市场对2026年行业前景乐观。",
        "source": "CNBC",
        "url": "https://example.com/sox-rally",
        "published": "2026-06-19",
        "search_keyword": "半导体",
    },

    # ---- 无关新闻（测试去重和过滤用） ----
    {
        "title": "比特币价格突破12万美元创历史新高",
        "summary": "受机构持续买入和ETF资金流入推动，比特币价格突破12万美元，加密货币总市值突破4万亿美元。",
        "source": "CoinDesk",
        "url": "https://example.com/bitcoin-120k",
        "published": "2026-06-21",
        "search_keyword": "",
    },
    {
        "title": "欧洲央行维持利率不变，拉加德称通胀仍需警惕",
        "summary": "欧洲央行在6月议息会议上维持基准利率不变，行长拉加德表示服务业通胀仍然偏高。",
        "source": "FT",
        "url": "https://example.com/ecb-rate",
        "published": "2026-06-21",
        "search_keyword": "",
    },
    {
        "title": "NVIDIA发布新一代AI芯片B200，性能提升4倍",  # 与第1条重复
        "summary": "NVIDIA在GTC大会上正式发布Blackwell B200 GPU，AI训练性能较上一代Hopper架构提升4倍，预计Q3量产交付。",
        "source": "Reuters",
        "url": "https://example.com/nvidia-b200",  # 相同URL
        "published": "2026-06-21",
        "search_keyword": "NVIDIA",
    },
]


def get_mock_news() -> list[dict]:
    """返回 mock 新闻列表."""
    return [dict(item) for item in MOCK_NEWS]  # 深拷贝，防止调用方修改
