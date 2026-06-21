# TDD — 股票分析器：技术设计文档

---

## 目录

- [1. High Level Design](#1-high-level-design)
  - [1.1 系统架构概览](#11-系统架构概览)
  - [1.2 技术选型](#12-技术选型)
  - [1.3 数据流](#13-数据流)
  - [1.4 模块划分与职责](#14-模块划分与职责)
  - [1.5 接口契约](#15-接口契约)
  - [1.6 错误处理策略](#16-错误处理策略)
- [2. Low Level Design](#2-low-level-design)
  - [2.1 `symbol_parser.py` — 代码解析器](#21-symbol_parserpy--代码解析器)
  - [2.2 `data/fetcher.py` — 行情获取](#22-datafetcherpy--行情获取)
  - [2.3 `data/news_fetcher.py` — 新闻获取](#23-datanews_fetcherpy--新闻获取)
  - [2.4 `analysis/sentiment.py` — 情感分析](#24-analysissentimentpy--情感分析)
  - [2.5 `analysis/advisor.py` — 操作建议](#25-analysisadvisorpy--操作建议)
  - [2.6 `output/reporter.py` — 报告生成](#26-outputreporterpy--报告生成)
  - [2.7 `main.py` — CLI 入口与 Pipeline 编排](#27-mainpy--cli-入口与-pipeline-编排)
  - [2.8 `mock_data.py` — Mock 数据](#28-mock_datapy--mock-数据)
- [3. 测试策略](#3-测试策略)
  - [3.1 测试金字塔](#31-测试金字塔)
  - [3.2 单元测试用例清单](#32-单元测试用例清单)
  - [3.3 集成测试场景](#33-集成测试场景)
  - [3.4 Mock 与 Fixture 设计](#34-mock-与-fixture-设计)
- [4. 优化路径](#4-优化路径)
  - [4.1 性能优化](#41-性能优化)
  - [4.2 准确率优化](#42-准确率优化)
  - [4.3 可维护性优化](#43-可维护性优化)

---

## 1. High Level Design

### 1.1 系统架构概览

```
                          main.py (Pipeline Orchestrator)
 ┌──────────────────────────────────────────────────────────────────────┐
 │                                                                        │
 │  ┌──────────┐   ┌──────────────┐   ┌──────────────┐   ┌────────────┐ │
 │  │ 1.Parse  │──▶│  2.Fetch     │──▶│  3.Analyze   │──▶│ 4.Output   │ │
 │  │ Symbols  │   │ 行情 + 新闻   │   │ 情感 + 建议   │   │ 终端 + 文件 │ │
 │  └──────────┘   └──────────────┘   └──────────────┘   └────────────┘ │
 │       │               │                   │                  │         │
 │       ▼               ▼                   ▼                  ▼         │
 │  symbol_parser   data/fetcher       analysis/sentiment  output/reporter│
 │                  data/news_fetcher  analysis/advisor                   │
 │                                                                        │
 └──────────────────────────────────────────────────────────────────────┘

                            ┌──────────────┐
                            │  mock_data   │  ◀── 全模块兜底
                            └──────────────┘
```

**架构模式**：Pipeline（管道-过滤器），每一步的输出是下一步的输入。无全局状态，每一步是纯函数或依赖注入。

**与 reporter 项目的一致性**：继承相同的 Pipeline 哲学，但 domain model 完全独立。

### 1.2 技术选型

| 层级 | 技术 | 版本 | 选型理由 |
|------|------|------|---------|
| Language | Python | ≥3.11 | 延续现有技术栈；`Self` 类型等新特性 |
| 行情数据 | `yfinance` | ≥0.2.40 | 免费、覆盖 CN/US/HK 三市场、无 API Key |
| 新闻获取 | `feedparser` | ≥6.0 | RSS 解析标准库，无需 API Key |
| HTTP | `requests` | ≥2.31 | feedparser 底层依赖，备选直接调用 NewsAPI |
| CLI框架 | `argparse` | stdlib | 标准库，无需额外依赖；题目场景参数简单 |
| 终端渲染 | `rich` | ≥13.0 | 表格/颜色/面板/Panel/Markdown 一站式 |
| 配置 | `pyyaml` | ≥6.0 | 配置文件模式（Phase 2） |
| 测试 | `pytest` + `pytest-cov` | ≥8.0 | 社区标准 |
| 代码质量 | `ruff` | ≥0.5 | 快；替代 flake8+isort |

**不引入的依赖**（MVP阶段）：

| 技术 | 原因 |
|------|------|
| `akshare` | A股备选数据源；MVP先不装，口头说明即可 |
| `openai` / `anthropic` | LLM 模式在 Phase 2；MVP不引入 |
| `sqlalchemy` / `sqlite3` | 不做持久化 |
| `streamlit` | Web 界面在 Phase 3 |

### 1.3 数据流

```
                        INPUT                  PROCESS                   OUTPUT
                   ───────────────     ──────────────────────     ───────────────────

  User CLI ──▶  ["513100","AAPL"]  ──▶  symbol_parser.parse()
                   │                           │
                   │                    StockInfo[] (normalized + market)
                   │                           │
                   ├───────────────────────────┤
                   │                           │
                   ▼                           ▼
            data/fetcher              data/news_fetcher
            .fetch_all()              .fetch_all()
                   │                           │
            MarketSnapshot[]           raw_articles: list[dict]
                   │                           │
                   │                           ▼
                   │              ┌─────────────────────────┐
                   │              │ analysis/sentiment      │
                   │              │ .analyze_batch()        │
                   │              │                         │
                   │              │  1. dedup (title/URL)   │
                   │              │  2. keyword_score()     │
                   │              │  3. negation_check()    │
                   │              │  4. classify()          │
                   │              │  5. map_to_symbols()    │
                   │              └──────────┬──────────────┘
                   │                         │
                   │                  NewsItem[] (labeled)
                   │                         │
                   ├─────────────────────────┤
                   │                         │
                   ▼                         ▼
              ┌─────────────────────────────────────┐
              │ analysis/advisor                    │
              │ .generate_advice()                  │
              │                                     │
              │  for each StockInfo:                │
              │    1. get MarketSnapshot            │
              │    2. get related NewsItem[]        │
              │    3. calc sentiment_bias           │
              │    4. lookup decision_matrix        │
              │    5. build StockAdvice             │
              └────────────────┬────────────────────┘
                               │
                        StockAdvice[]
                               │
                               ▼
              ┌─────────────────────────────────────┐
              │ output/reporter                     │
              │ .render() → DailyBriefing           │
              │                                     │
              │  → terminal (rich)                  │
              │  → report.md                        │
              │  → briefing.json (--output json)    │
              └─────────────────────────────────────┘
```

### 1.4 模块划分与职责

```
stock_analyzer/
├── main.py                 # 入口：CLI解析 + Pipeline编排 + 异常兜底
├── symbol_parser.py        # 代码格式识别 + 市场分类 + yfinance格式转换
├── mock_data.py            # 内置mock数据（3个市场、10条新闻）
├── models.py               # 所有 dataclass 定义（共享数据结构）
├── data/
│   ├── __init__.py
│   ├── fetcher.py          # yfinance 行情获取 + 降级逻辑
│   └── news_fetcher.py     # RSS 新闻获取 + 关键词构造 + 降级逻辑
├── analysis/
│   ├── __init__.py
│   ├── sentiment.py        # 情感分析引擎（规则 + LLM接口预留）
│   └── advisor.py          # 操作建议生成（决策矩阵）
├── output/
│   ├── __init__.py
│   └── reporter.py         # rich 终端渲染 + Markdown 文件生成
├── requirements.txt
└── README.md
```

| 模块 | 职责 | 依赖 | 是否访问外部 |
|------|------|------|-------------|
| `models.py` | 所有 dataclass 统一定义 | 无 | 否 |
| `symbol_parser.py` | 输入解析、格式识别、标准化 | `models` | 否 |
| `data/fetcher.py` | 行情获取、超时、重试、降级 | `models`, `yfinance` | 是 (Yahoo Finance) |
| `data/news_fetcher.py` | 关键词构造、RSS获取、去重 | `models`, `feedparser` | 是 (Google News) |
| `analysis/sentiment.py` | 情感打分、否定处理、分类 | `models` | 否 |
| `analysis/advisor.py` | 决策矩阵、建议生成 | `models` | 否 |
| `output/reporter.py` | 渲染终端 + 写文件 | `models`, `rich` | 否 (只写本地文件) |
| `main.py` | 编排所有步骤、处理顶层异常 | 所有模块 | 否 |
| `mock_data.py` | 静态 mock 数据 | `models` | 否 |

### 1.5 接口契约

每层之间的数据传递使用明确的数据类，**禁止在模块间传递裸 dict**。

```python
# pipeline 中各阶段的输入输出类型签名

# Stage 0: Input
raw_input: list[str]  # CLI args, e.g. ["513100", "AAPL", "0700.HK"]

# Stage 1: Parse
parsed: list[StockInfo]

# Stage 2: Fetch (并行)
snapshots: list[MarketSnapshot]
raw_news: list[dict]  # 原始新闻，尚未结构化（来自 feedparser）

# Stage 3: Analyze
news_items: list[NewsItem]  # sentiment.py 输出
advice: list[StockAdvice]    # advisor.py 输出

# Stage 4: Output
# → DailyBriefing (reporter内部构建)
# → terminal stdout + report.md 文件
```

### 1.6 错误处理策略

```
                         ┌─────────────────┐
                         │   异常发生        │
                         └────────┬────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │  异常类型判断               │
                    └─────────────┬─────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          ▼                       ▼                       ▼
  ┌──────────────┐       ┌──────────────┐       ┌──────────────┐
  │ 单只股票失败  │       │ 全部数据源失败 │       │ 部分新闻失败  │
  └──────┬───────┘       └──────┬───────┘       └──────┬───────┘
         │                      │                      │
         ▼                      ▼                      ▼
  ┌──────────────┐       ┌──────────────┐       ┌──────────────┐
  │跳过该股票     │       │切换 mock_data │       │标注 data_status│
  │继续处理其余   │       │全量 mock 兜底 │       │= "partial"    │
  │WARNING 日志   │       │报告顶部警告   │       │继续生成报告   │
  └──────────────┘       └──────────────┘       └──────────────┘
```

**原则**：

1. **永不崩溃** — 任何外部调用失败都有兜底路径
2. **降级透明** — 数据状态（live/mock/partial）在报告顶部可见
3. **单点不影响全局** — 一只股票失败不阻塞其他股票
4. **全部失败才切 mock** — 只要有一只股票数据可用，就用 live 模式

**实现方式**：

```python
# 在每个 fetcher 内部 try/except
def fetch_snapshot(symbol: str) -> MarketSnapshot | None:
    try:
        return _do_fetch(symbol)
    except Exception as e:
        logger.warning(f"Failed to fetch {symbol}: {e}")
        return None

# 在 main.py 中汇总判断
def should_use_mock(snapshots: list[MarketSnapshot | None]) -> bool:
    return all(s is None for s in snapshots)
```

---

## 2. Low Level Design

### 2.1 `symbol_parser.py` — 代码解析器

#### 职责

将用户输入的任意格式股票代码统一转换为 `StockInfo`，自动识别市场和 yfinance 标准格式。

#### 算法

```
输入: raw_symbol (str)
输出: StockInfo

1. 去除首尾空格，转大写
2. 如果包含 ".":
     → 用户已指定后缀，直接解析 market
     → .HK → HK | .SS/.SH → CN | .SZ → CN
3. 如果纯字母 (1-5位):
     → market = US, normalized = raw
4. 如果纯数字:
     4a. 长度 == 6:
         开头 60/51 → 上交所 → .SS
         开头 00/30 → 深交所 → .SZ
         开盘 68 → 科创板 → .SS
     4b. 长度 == 5: 港股 → 补零到4位 + .HK
     4c. 长度 == 4: 港股 → .HK
     4d. 其他: → UNKNOWN (后续会报错)
5. 返回 StockInfo
```

#### 函数签名

```python
def parse_symbol(raw: str) -> StockInfo:
    """
    Parse a single raw symbol into a StockInfo.

    Raises:
        SymbolParseError: if format is unrecognized.
    """

def parse_symbols(raw_list: list[str]) -> list[StockInfo]:
    """
    Parse a list of raw symbols. Invalid ones log a warning and are skipped.
    Returns only successfully parsed symbols.
    """

def normalize_a_share(code: str) -> str:
    """Convert A-share 6-digit code to yfinance suffix (.SS or .SZ)."""

def normalize_hk_share(code: str) -> str:
    """Convert HK stock code to yfinance format (XXXX.HK)."""
```

#### 边界情况

| 输入 | 期望输出 | 说明 |
|------|---------|------|
| `"513100"` | `513100.SS`, CN | A股ETF |
| `"600519"` | `600519.SS`, CN | 上交所 |
| `"000001"` | `000001.SZ`, CN | 深交所主板 |
| `"300750"` | `300750.SZ`, CN | 创业板 |
| `"688981"` | `688981.SS`, CN | 科创板 |
| `"AAPL"` | `AAPL`, US | 美股 |
| `"0700"` | `0700.HK`, HK | 港股4位 |
| `"00700"` | `0700.HK`, HK | 港股5位补零 |
| `"9988"` | `9988.HK`, HK | 港股 |
| `"0700.HK"` | `0700.HK`, HK | 已带后缀 |
| `"600519.SH"` | `600519.SS`, CN | 已带SH后缀 |
| `"123"` | `SymbolParseError` | 无法识别 |
| `""` | `SymbolParseError` | 空字符串 |

### 2.2 `data/fetcher.py` — 行情获取

#### 职责

通过 yfinance 获取单只或多只股票的实时/收盘行情，带超时和降级。

#### 架构

```
fetch_all(symbols: list[str]) → list[MarketSnapshot | None]
    │
    ├── 并行调用 fetch_one(symbol) × N
    │       │
    │       ├── yf.Ticker(normalized).history(period="1d")
    │       ├── yf.Ticker(normalized).fast_info  (更快，有限字段)
    │       └── try/except → 返回 None
    │
    └── 收集结果，all(None) → 触发 mock fallback
```

#### 函数签名

```python
def fetch_one(symbol: str, timeout: float = 5.0) -> MarketSnapshot | None:
    """
    Fetch latest market data for a single normalized symbol.

    Args:
        symbol: yfinance-normalized ticker (e.g. "513100.SS")
        timeout: request timeout in seconds

    Returns:
        MarketSnapshot if successful, None if failed.
    """

def fetch_all(
    stocks: list[StockInfo],
    timeout: float = 5.0
) -> list[MarketSnapshot | None]:
    """
    Fetch market data for all stocks. Failures return None per position.
    Uses sequential requests to avoid yfinance rate-limiting.
    """

def _ticker_to_snapshot(ticker, stock: StockInfo) -> MarketSnapshot:
    """Convert yfinance Ticker object to our MarketSnapshot dataclass."""

def _detect_market_status(snapshot: MarketSnapshot) -> str:
    """
    Heuristic: if data_time is within 30 min of now → "盘中",
    if more than 6h old → "已收盘", etc.
    """
```

#### yfinance 字段映射

| MarketSnapshot 字段 | yfinance 来源 | fallback |
|---------------------|---------------|----------|
| `price` | `fast_info.last_price` → `history['Close'].iloc[-1]` | 0.0 |
| `change_pct` | `(price - prev_close) / prev_close * 100` | 0.0 |
| `prev_close` | `fast_info.previous_close` → `history['Close'].iloc[-2]` | price |
| `volume` | `fast_info.last_volume` → `history['Volume'].iloc[-1]` | 0 |
| `data_time` | `datetime.now()` (yfinance 不精确提供时间) | - |
| `name` | `ticker.info.get('longName')` → `ticker.info.get('shortName')` → symbol | symbol |

#### 容错设计

```python
# 逐只获取，不做批量（yfinance 批量接口不稳定）
# 每只股票独立 try/except，一只失败不影响其他

def fetch_all(stocks: list[StockInfo]) -> list[MarketSnapshot | None]:
    results = []
    for stock in stocks:
        result = fetch_one(stock.normalized_symbol)
        results.append(result)
    return results
```

### 2.3 `data/news_fetcher.py` — 新闻获取

#### 职责

根据股票信息构造搜索关键词，从 RSS 源获取新闻，做基础去重。

#### 架构

```
fetch_all(stocks, theme) → list[dict] (raw articles)
    │
    ├── 1. build_keywords(stocks, theme) → list[str]
    │       │
    │       ├── 取每只股票 name 中的关键词
    │       ├── 取 theme（如"AI产业链"）
    │       └── 取预置的行业关键词映射
    │
    ├── 2. 每个关键词 → Google News RSS URL
    │       https://news.google.com/rss/search?q={keyword}&hl=zh-CN&ceid=CN:zh-Hans
    │
    ├── 3. feedparser.parse(url) → entries
    │
    ├── 4. 合并所有 entries，按 published 降序
    │
    ├── 5. 去重：相同 title (fuzzy) 或相同 url → 保留最早
    │
    └── 6. 返回前 20 条
```

#### 函数签名

```python
def build_keywords(stocks: list[StockInfo], theme: str | None = None) -> list[str]:
    """
    Build search keywords from stock names and optional theme.

    Example:
        stocks=[513100(纳指科技ETF), 513310(中韩半导体ETF)]
        theme="AI产业链"
        → ["纳指科技", "纳斯达克科技", "NVIDIA", "AI芯片",
           "中韩半导体", "三星", "SK海力士", "半导体",
           "AI产业链", "人工智能"]
    """

def build_rss_url(keyword: str, lang: str = "zh-CN") -> str:
    """Construct Google News RSS URL for a keyword."""

def fetch_articles(keywords: list[str], max_per_keyword: int = 5) -> list[dict]:
    """
    Fetch news articles from RSS for all keywords.
    Returns list of raw article dicts: {title, summary, url, source, published}.
    """

def deduplicate(articles: list[dict]) -> list[dict]:
    """
    Deduplicate by:
    1. Exact URL match → drop duplicate
    2. Fuzzy title match (difflib ratio > 0.85) → keep first
    """

def fetch_all(
    stocks: list[StockInfo],
    theme: str | None = None,
    max_articles: int = 20
) -> list[dict]:
    """Main entry: keywords → RSS → dedup → top-N."""
```

#### 关键词构造策略

```python
# 预置映射表：主题 → 补充关键词
THEME_KEYWORDS: dict[str, list[str]] = {
    "AI产业链": ["人工智能", "AI芯片", "GPU", "大模型", "算力", "自动驾驶",
                "machine learning", "NVIDIA", "OpenAI", "HBM"],
    "新能源": ["光伏", "锂电", "储能", "新能源汽车", "风电",
              "solar", "EV battery", "Tesla", "CATL", "比亚迪"],
    "半导体": ["芯片", "晶圆", "光刻", "封装", "HBM", "EDA",
              "semiconductor", "TSMC", "ASML", "chip"],
}

def build_keywords(stocks: list[StockInfo], theme: str | None = None) -> list[str]:
    keywords = []

    # 1. 股票名称关键词
    for stock in stocks:
        keywords.append(stock.name)  # e.g. "纳指科技ETF"
        # 从名称中提子词（简化：空格/连字符分词）
        keywords.extend(stock.name.replace("ETF", "").split())

    # 2. Theme 关键词
    if theme and theme in THEME_KEYWORDS:
        keywords.extend(THEME_KEYWORDS[theme])

    # 3. 去重 + 限制数量（最多15个关键词，避免RSS请求过多）
    return list(dict.fromkeys(keywords))[:15]
```

#### 容错设计

```python
def fetch_articles(keywords: list[str]) -> list[dict]:
    all_articles = []
    for kw in keywords:
        try:
            url = build_rss_url(kw)
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:  # 每个关键词最多5条
                all_articles.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", ""),
                    "url": entry.get("link", ""),
                    "source": entry.get("source", {}).get("title", ""),
                    "published": entry.get("published", ""),
                    "search_keyword": kw,
                })
        except Exception:
            continue  # 单个关键词失败不影响其他

    return all_articles
```

### 2.4 `analysis/sentiment.py` — 情感分析

#### 职责

对每条新闻进行情感分类（利好/利空/中性），并标注影响哪些持仓标的。

#### 算法（两阶段）

```
Phase 1 — 情感打分
───────────────────
input:  NewsItem.title + NewsItem.summary
output: sentiment_score (float), sentiment_label (str)

1. 文本预处理：全角→半角，统一小写（英文部分）
2. 扫描 POSITIVE_WORDS，每命中 +1
3. 扫描 NEGATIVE_WORDS，每命中 -1
4. 扫描 NEGATION_PREFIXES，若在命中词前 3 个 token 内出现 → 反转该词得分
5. sum = positive_score - negative_score
6. 归一化：score = sum / (len(words) / 100)  # 按文本长度归一化
7. 分类：
     score >  0.3 → "positive"
     score < -0.3 → "negative"
     其他         → "neutral"


Phase 2 — 标的映射
───────────────────
input:  NewsItem, list[StockInfo]
output: affected_symbols (list[str])

1. 对每只 StockInfo，取其 name + keywords
2. 若新闻 title + summary 中包含该标的的 name 或 keywords 的任意子串
   → 标记为 affected
3. 若新闻不匹配任何标的 → relevance = 0，后续可能被丢弃
```

#### 函数签名

```python
# 情感词典（模块级常量）
POSITIVE_CN: list[str]   # 中文利好词
NEGATIVE_CN: list[str]   # 中文利空词
POSITIVE_EN: list[str]   # 英文利好词
NEGATIVE_EN: list[str]   # 英文利空词
NEGATION_CN: list[str]   # 中文否定词
NEGATION_EN: list[str]   # 英文否定词


def tokenize(text: str) -> list[str]:
    """
    Simple whitespace + punctuation tokenization.
    For Chinese: character-level bigrams for keyword matching.
    """

def sentiment_score(title: str, summary: str) -> tuple[float, str]:
    """
    Calculate sentiment score and label for a news item.

    Returns:
        (score, label) where label ∈ {"positive", "negative", "neutral"}
    """

def map_to_symbols(
    article: dict,
    stocks: list[StockInfo]
) -> tuple[list[str], float]:
    """
    Determine which stocks this article affects.

    Returns:
        (affected_normalized_symbols, max_relevance_score)
    """

def analyze_batch(
    articles: list[dict],
    stocks: list[StockInfo]
) -> list[NewsItem]:
    """
    Full pipeline for a batch of raw articles:
    1. sentiment_score()
    2. map_to_symbols()
    3. build NewsItem
    4. filter out articles with no affected stocks AND relevance < 0.3
    5. sort by relevance desc
    """

def has_negation(word_idx: int, tokens: list[str]) -> bool:
    """Check if a negation word appears within 3 tokens before word_idx."""

# ---- LLM 接口预留 ----
def analyze_with_llm(
    articles: list[dict],
    stocks: list[StockInfo],
    model: str = "claude-sonnet-4-6"
) -> list[NewsItem]:
    """(Phase 2) Use LLM for semantic sentiment analysis."""
    raise NotImplementedError("LLM mode not available in MVP")
```

#### 否定处理示例

```python
# "不会下跌" → 不应被判为利空
# tokens: ["不会", "下跌"]
# 1. "下跌" 命中 NEGATIVE_CN → 得分 -1
# 2. 回溯3个token内发现 "不会" 命中 NEGATION_CN → 得分反转 → 0
# 3. 最终得分不受"下跌"影响

# "有限增长" → 不应被判为利好
# 1. "增长" 命中 POSITIVE_CN → 得分 +1
# 2. 回溯3个token内发现 "有限" 命中 NEGATION_CN → 得分反转 → 0
```

### 2.5 `analysis/advisor.py` — 操作建议

#### 职责

综合单只股票的行情涨跌和相关新闻的情感偏向，输出操作建议。

#### 决策矩阵

```python
# 矩阵维度：
#   行 = 行情涨跌分桶: big_up | small_up | flat | small_down | big_down
#   列 = 消息面倾向: bullish | neutral | bearish
#
# 矩阵内容: (action, confidence)

DECISION_MATRIX = {
    # (price_bucket, sentiment_bias) → (action, confidence)
    ("big_up",    "bullish"):  ("accumulate", "high"),
    ("big_up",    "neutral"):  ("hold",       "high"),
    ("big_up",    "bearish"):  ("watch",      "medium"),  # 大涨但消息偏空 → 警惕
    ("small_up",  "bullish"):  ("hold",       "medium"),
    ("small_up",  "neutral"):  ("hold",       "high"),
    ("small_up",  "bearish"):  ("watch",      "medium"),
    ("flat",      "bullish"):  ("watch",      "medium"),
    ("flat",      "neutral"):  ("hold",       "high"),
    ("flat",      "bearish"):  ("watch",      "medium"),
    ("small_down","bullish"):  ("watch",      "medium"),  # 小跌但消息偏多 → 关注抄底
    ("small_down","neutral"):  ("hold",       "medium"),
    ("small_down","bearish"):  ("hold",       "medium"),
    ("big_down",  "bullish"):  ("accumulate", "medium"),  # 大跌+消息好 → 抄底机会
    ("big_down",  "neutral"):  ("watch",      "medium"),
    ("big_down",  "bearish"):  ("reduce",     "high"),    # 大跌+消息差 → 减仓
}
```

#### 算法

```
输入: MarketSnapshot, list[NewsItem], thresholds
输出: StockAdvice

1. 行情分桶:
     change_pct >  big_up_threshold → "big_up"
     change_pct >  attention_threshold → "small_up"
     change_pct > -attention_threshold → "flat"
     change_pct >  big_down_threshold → "small_down"
     其他 → "big_down"

2. 消息面倾向:
     bias = (positive_count - negative_count) / max(total_count, 1)
     bias >  0.3 → "bullish"
     bias < -0.3 → "bearish"
     其他 → "neutral"

3. 查表: DECISION_MATRIX[(price_bucket, sentiment_bias)]

4. 构造理由:
     - 行情驱动: "{name} 今日涨/跌 {pct}%，属于{'大' if big else '小'}幅{'上涨' if up else '下跌'}"
     - 消息驱动: "消息面偏{'多' if bullish else '空' if bearish else '中性'} ({pos}利好/{neg}利空)"
     - 若为ETF: 可额外提及关键成分股动态

5. 返回 StockAdvice
```

#### 函数签名

```python
# 阈值配置（可覆盖）
@dataclass
class Thresholds:
    big_up: float = 3.0        # 大涨阈值 %
    big_down: float = -3.0     # 大跌阈值 %
    attention: float = 1.5     # 关注阈值 %
    sentiment_bullish: float = 0.3   # 偏多阈值
    sentiment_bearish: float = -0.3  # 偏空阈值


def bucket_price(change_pct: float, thresholds: Thresholds) -> str:
    """Classify price change into bucket."""

def bucket_sentiment(positive: int, negative: int, total: int) -> str:
    """Classify sentiment bias into bucket."""

def generate_reason(
    stock: StockInfo,
    snapshot: MarketSnapshot,
    news_items: list[NewsItem],
    sentiment_bias: str
) -> list[str]:
    """Generate 1-2 human-readable reasons for the advice."""

def generate_one(
    stock: StockInfo,
    snapshot: MarketSnapshot,
    news_items: list[NewsItem],
    thresholds: Thresholds | None = None
) -> StockAdvice:
    """Generate advice for a single stock."""

def generate_all(
    stocks: list[StockInfo],
    snapshots: list[MarketSnapshot | None],
    news_items: list[NewsItem],
    thresholds: Thresholds | None = None
) -> list[StockAdvice | None]:
    """Generate advice for all stocks. Returns None for stocks without data."""
```

### 2.6 `output/reporter.py` — 报告生成

#### 职责

将分析结果渲染为终端彩色输出和 Markdown 文件。

#### 终端输出结构（rich 布局）

```
┌──────────────────────────────────────────┐
│  Panel: 📊 每日投资简报                   │
│  subtitle: 日期 / 数据状态 / 免责声明      │
├──────────────────────────────────────────┤
│  Panel: 📈 行情快照                       │
│  Table: 标的 | 市场 | 最新价 | 涨跌幅 | ... │
├──────────────────────────────────────────┤
│  Panel: 📰 关键消息                       │
│  (per stock)                             │
│  Text: "### 标的名称 (symbol)"            │
│  Table: # | 情感 | 标题 | 来源            │
│  Text: "> 📊 消息面倾向：偏多 (2/1/0)"    │
├──────────────────────────────────────────┤
│  Panel: 💡 操作建议                       │
│  Table: 标的 | 建议 | 置信度 | 理由       │
├──────────────────────────────────────────┤
│  Panel: 📋 被过滤的新闻                   │
│  (collapsed by default, --verbose 展开)   │
├──────────────────────────────────────────┤
│  Text: "Generated by Stock Analyzer v0.1"│
└──────────────────────────────────────────┘
```

#### 函数签名

```python
def render_terminal(briefing: DailyBriefing, verbose: bool = False) -> None:
    """Render briefing to terminal using rich."""

def render_markdown(briefing: DailyBriefing) -> str:
    """Render briefing as Markdown string."""

def write_report(briefing: DailyBriefing, output_dir: Path = Path(".")) -> Path:
    """
    Write report.md to output_dir.
    Returns the path to the written file.
    """

def render_json(briefing: DailyBriefing) -> str:
    """(Phase 2) Render briefing as JSON string."""

def render(
    briefing: DailyBriefing,
    output_dir: Path = Path("."),
    formats: list[str] = ["terminal", "markdown"],
    verbose: bool = False
) -> dict[str, Path | None]:
    """
    Main entry: render in all requested formats.
    Returns dict mapping format → output path (or None for terminal).
    """
```

#### Markdown 模板（内嵌）

```python
MARKDOWN_TEMPLATE = """\
# 📊 每日投资简报

**日期**: {date}
**数据状态**: {data_status_emoji} {data_status_label}
**免责声明**: ⚠️ 本报告由AI生成，仅供参考，不构成投资建议。投资有风险，决策需谨慎。

---

## 📈 行情快照

{market_table}

---

## 📰 关键消息

{news_sections}

---

## 💡 操作建议

{advice_table}

---

## 📋 被过滤的新闻 ({dropped_count}条)

{dropped_list}

---

*Generated by Stock Analyzer v0.1.0 at {timestamp}*
"""
```

### 2.7 `main.py` — CLI 入口与 Pipeline 编排

#### 职责

解析命令行参数，编排 pipeline 各阶段，处理顶层异常。

#### CLI 设计

```bash
# 基本用法
python main.py --symbols 513100 513310 --theme "AI产业链"

# 多个市场混输
python main.py --symbols AAPL 600519.SH 0700.HK

# 详细输出（显示被过滤的新闻）
python main.py --symbols AAPL NVDA --verbose

# 指定输出目录
python main.py --symbols 513100 --output-dir ./reports

# 使用 mock 数据（强制离线演示）
python main.py --symbols 513100 513310 --mock

# 输出 JSON
python main.py --symbols AAPL --output json
```

#### argparse 定义

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock-analyzer",
        description="多市场股票分析器 — 每日消息面 + 操作建议",
    )
    parser.add_argument(
        "--symbols", "-s",
        nargs="+",
        required=True,
        help="股票代码列表，支持A股/美股/港股，如: 600519 AAPL 0700.HK",
    )
    parser.add_argument(
        "--theme", "-t",
        default=None,
        help="关注主题，用于补充新闻搜索关键词，如: AI产业链 新能源",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=Path("."),
        help="报告输出目录 (默认: 当前目录)",
    )
    parser.add_argument(
        "--output", "-f",
        choices=["terminal", "markdown", "json"],
        default=["terminal", "markdown"],
        nargs="+",
        help="输出格式",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="强制使用内置 mock 数据（用于离线演示）",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示被过滤的新闻详情",
    )
    return parser
```

#### Pipeline 编排

```python
def run_pipeline(
    raw_symbols: list[str],
    theme: str | None = None,
    use_mock: bool = False,
    output_dir: Path = Path("."),
    output_formats: list[str] = ["terminal", "markdown"],
    verbose: bool = False,
) -> DailyBriefing:
    """
    Execute the full pipeline.

    Steps:
        1. Parse symbols → list[StockInfo]
        2. If use_mock: use mock data
           Else:
             a. Fetch market data → list[MarketSnapshot | None]
             b. Fetch news → list[dict]
             c. If all snapshots failed → fallback to mock
        3. Analyze sentiment → list[NewsItem]
        4. Generate advice → list[StockAdvice | None]
        5. Build DailyBriefing
        6. Render output
        7. Return briefing
    """
```

#### 异常处理流程图

```
main()
  │
  ├── try:
  │     ├── parse_symbols()
  │     │     └── SymbolParseError → print warning, skip bad symbol
  │     │
  │     ├── if --mock: use mock
  │     │   else: fetch_all() + fetch_articles()
  │     │     └── exception → log warning, continue with None
  │     │     └── all failed → switch to mock
  │     │
  │     ├── analyze_batch()
  │     ├── generate_all()
  │     ├── build DailyBriefing
  │     └── render()
  │
  └── except KeyboardInterrupt:
        print("Interrupted")
        sys.exit(130)
      except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
```

### 2.8 `mock_data.py` — Mock 数据

#### 职责

提供一组静态的、覆盖三个市场的 mock 数据，用于：
1. 离线演示（`--mock`）
2. 网络不可用时的自动降级
3. 单元测试

#### 数据结构

```python
MOCK_SNAPSHOTS: dict[str, MarketSnapshot] = {
    "513100.SS": MarketSnapshot(
        symbol="513100.SS",
        name="纳指科技ETF",
        market="CN",
        price=1.856,
        change_pct=-1.2,
        change_amount=-0.023,
        volume=120_000_000,
        prev_close=1.879,
        data_time=datetime(2026, 6, 21, 15, 0, 0),
        market_status="已收盘",
        timezone="Asia/Shanghai",
    ),
    "513310.SS": MarketSnapshot(...),  # 中韩半导体ETF
    "AAPL": MarketSnapshot(...),        # Apple
    "0700.HK": MarketSnapshot(...),     # 腾讯
    "600519.SS": MarketSnapshot(...),   # 茅台
}

MOCK_NEWS: list[dict] = [
    {
        "title": "NVIDIA发布新一代AI芯片B200，性能提升4倍",
        "summary": "NVIDIA在GTC大会上正式发布...",
        "source": "Reuters",
        "url": "https://example.com/nvidia-b200",
        "published": "2026-06-21",
        "search_keyword": "AI芯片",
    },
    # ... 共10-15条，覆盖中文/英文、利好/利空/中性
]
```

#### 函数签名

```python
def get_mock_snapshots(symbols: list[str]) -> list[MarketSnapshot | None]:
    """
    Return mock snapshots for the requested symbols.
    Unknown symbols return None at their position.
    """

def get_mock_news() -> list[dict]:
    """Return mock news articles."""

def get_default_symbols() -> list[str]:
    """Return the default demo symbols (513100, 513310, AAPL)."""
```

---

## 3. 测试策略

### 3.1 测试金字塔

```
         ┌─────────┐
         │  E2E    │  1-2 个：全 pipeline 跑通（mock + live）
         │  2 tests│
        ┌┴─────────┴┐
        │Integration│  3-4 个：模块间契约、数据流完整性
        │  4 tests  │
       ┌┴───────────┴┐
       │    Unit      │  ~15 个：每个函数的核心逻辑 + 边界
       │  ~15 tests   │
      ┌┴──────────────┴┐
      │   Static        │  ruff lint + mypy type check
      │   (pre-commit)  │
      └────────────────┘
```

### 3.2 单元测试用例清单

#### `test_symbol_parser.py`

| # | 测试用例 | 输入 | 期望 |
|---|---------|------|------|
| 1 | `test_parse_a_share_shanghai` | `"600519"` | `StockInfo("600519.SS", "CN")` |
| 2 | `test_parse_a_share_shenzhen` | `"000001"` | `StockInfo("000001.SZ", "CN")` |
| 3 | `test_parse_a_share_gem` | `"300750"` | `StockInfo("300750.SZ", "CN")` |
| 4 | `test_parse_a_share_star` | `"688981"` | `StockInfo("688981.SS", "CN")` |
| 5 | `test_parse_us_stock` | `"AAPL"` | `StockInfo("AAPL", "US")` |
| 6 | `test_parse_hk_4digit` | `"0700"` | `StockInfo("0700.HK", "HK")` |
| 7 | `test_parse_hk_5digit` | `"00700"` | `StockInfo("0700.HK", "HK")` |
| 8 | `test_parse_with_suffix_hk` | `"0700.HK"` | `StockInfo("0700.HK", "HK")` |
| 9 | `test_parse_with_suffix_sh` | `"600519.SH"` | `StockInfo("600519.SS", "CN")` |
| 10 | `test_parse_empty_raises` | `""` | `SymbolParseError` |
| 11 | `test_parse_invalid_raises` | `"123"` | `SymbolParseError` |
| 12 | `test_parse_symbols_mixed` | `["AAPL", "bad", "0700"]` | 2个成功, 1个跳过 |

#### `test_sentiment.py`

| # | 测试用例 | 输入 | 期望 |
|---|---------|------|------|
| 1 | `test_positive_cn` | "NVIDIA 发布新品，业绩超预期" | `("positive", score > 0)` |
| 2 | `test_negative_cn` | "芯片出口被制裁，行业面临下跌风险" | `("negative", score < 0)` |
| 3 | `test_neutral_cn` | "今日市场窄幅震荡" | `("neutral", score ≈ 0)` |
| 4 | `test_positive_en` | "NVIDIA beats earnings, record high" | `("positive", ...)` |
| 5 | `test_negative_en` | "sanctions and restrictions loom" | `("negative", ...)` |
| 6 | `test_negation_cn` | "分析认为不会出现大幅下跌" | `("neutral", ...)` (下跌被"不会"否定) |
| 7 | `test_negation_en` | "unlikely to face sanctions" | `("neutral", ...)` |
| 8 | `test_mixed_signals` | "产品突破但面临诉讼" | `("neutral", ...)` |
| 9 | `test_map_to_symbols_exact` | "纳指科技ETF今日下跌" + stocks含513100 | `affected=["513100.SS"]` |
| 10 | `test_map_to_symbols_keyword` | "NVIDIA发布新GPU" + stocks含513100(关键词含NVIDIA) | `affected=["513100.SS"]` |
| 11 | `test_map_to_symbols_none` | "比特币突破10万美元" + 无相关持仓 | `affected=[]` |

#### `test_advisor.py`

| # | 测试用例 | 输入 | 期望 |
|---|---------|------|------|
| 1 | `test_big_up_bullish` | change=+4%, bias="bullish" | `action="accumulate", confidence="high"` |
| 2 | `test_big_down_bearish` | change=-4%, bias="bearish" | `action="reduce", confidence="high"` |
| 3 | `test_flat_neutral` | change=+0.5%, bias="neutral" | `action="hold", confidence="high"` |
| 4 | `test_small_down_bullish` | change=-2%, bias="bullish" | `action="watch"` (关注抄底) |
| 5 | `test_big_up_bearish` | change=+4%, bias="bearish" | `action="watch"` (警惕追高) |
| 6 | `test_no_news_default_neutral` | change=-2%, news=[] | `bias="neutral"` |
| 7 | `test_reason_generation` | - | 理由中包含股票名和涨跌幅 |
| 8 | `test_none_snapshot_returns_none` | snapshot=None | 返回 None |

#### `test_news_fetcher.py`

| # | 测试用例 | 输入 | 期望 |
|---|---------|------|------|
| 1 | `test_build_keywords_with_theme` | stocks + theme | 关键词含股票名和主题词 |
| 2 | `test_build_keywords_without_theme` | stocks only | 只含股票名关键词 |
| 3 | `test_build_rss_url` | keyword | 返回有效URL |
| 4 | `test_deduplicate_exact_url` | 2条同URL | 保留1条 |
| 5 | `test_deduplicate_fuzzy_title` | 2条标题相似度>85% | 保留1条 |

### 3.3 集成测试场景

| # | 场景 | 验证点 |
|---|------|--------|
| **I1** | 完整 pipeline（mock 模式） | 输入3只股票 → 输出完整 DailyBriefing，无异常 |
| **I2** | 完整 pipeline（live 模式） | 输入2只真实股票 → 能获取到数据 → 输出报告 |
| **I3** | 部分失败场景 | 输入1只有效+1只无效代码 → 有效的那只有结果，无效的被跳过 |
| **I4** | 全失败降级 | 断网运行 → 自动切换到 mock → report 顶部标注"模拟数据" |
| **I5** | Markdown 文件输出 | 运行后 report.md 存在且内容格式正确 |

### 3.4 Mock 与 Fixture 设计

```python
# conftest.py — 共享 fixtures

@pytest.fixture
def sample_stocks():
    """3只典型股票，覆盖三个市场"""
    return [
        StockInfo(input_symbol="513100", normalized_symbol="513100.SS",
                   market="CN", name="纳指科技ETF", sector=None, components=[]),
        StockInfo(input_symbol="AAPL", normalized_symbol="AAPL",
                   market="US", name="Apple Inc.", sector=None, components=[]),
        StockInfo(input_symbol="0700", normalized_symbol="0700.HK",
                   market="HK", name="腾讯控股", sector=None, components=[]),
    ]

@pytest.fixture
def sample_snapshots(sample_stocks):
    """与 sample_stocks 对应的行情数据"""
    return [...]

@pytest.fixture
def sample_news():
    """10条 mock 新闻，覆盖各情感方向"""
    return [...]

@pytest.fixture
def sample_briefing(sample_stocks, sample_snapshots, sample_news):
    """完整的 DailyBriefing，用于测试 reporter"""
    return DailyBriefing(...)


# 网络相关测试用 pytest.mark
@pytest.mark.network  # 需要网络
def test_fetch_live():
    ...

@pytest.mark.skipif(no_network(), reason="No network available")
def test_fetch_live_conditional():
    ...
```

### 3.5 推荐测试文件结构

```
stock_analyzer/
├── tests/
│   ├── __init__.py
│   ├── conftest.py                  # 共享 fixtures
│   ├── test_symbol_parser.py        # ~12 tests
│   ├── test_fetcher.py              # ~5 tests (含 mock yfinance)
│   ├── test_news_fetcher.py         # ~6 tests
│   ├── test_sentiment.py            # ~11 tests
│   ├── test_advisor.py              # ~8 tests
│   ├── test_reporter.py             # ~4 tests
│   └── test_integration.py          # ~5 tests
└── ...
```

---

## 4. 优化路径

### 4.1 性能优化

| # | 优化项 | 当前状态 | 目标 | 方案 |
|---|--------|---------|------|------|
| **P1** | 并发获取行情 | 顺序请求 N 只股票 | 并发（ThreadPoolExecutor） | yfinance 是 IO-bound，`concurrent.futures` 即可，N=5 只时从 ~8s 降到 ~2s |
| **P2** | 新闻 RSS 请求合并 | 每个关键词一个 HTTP 请求 | 批量关键词 OR 用 NewsAPI 单次请求 | NewsAPI 免费 tier 500req/day；或 Google News 用 `OR` 连接多个关键词 |
| **P3** | 缓存行情数据 | 每次运行都重新请求 | 缓存5分钟内的行情 | 本地 JSON 文件缓存，key = symbol + 日期，避免短时间重复运行重复请求 |

#### P1 具体方案

```python
# 当前（顺序）
def fetch_all(stocks):
    return [fetch_one(s) for s in stocks]

# 优化后（并发）
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_all(stocks, max_workers=5):
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, s): s for s in stocks}
        results = {}
        for future in as_completed(futures):
            stock = futures[future]
            try:
                results[stock] = future.result(timeout=10)
            except Exception:
                results[stock] = None
    return [results[s] for s in stocks]
```

#### P3 具体方案

```python
# 简易文件缓存
import json
from pathlib import Path
from datetime import datetime, timedelta

CACHE_DIR = Path.home() / ".cache" / "stock_analyzer"
CACHE_TTL = timedelta(minutes=5)

def _cache_key(symbol: str) -> Path:
    return CACHE_DIR / f"{symbol}_{datetime.now():%Y%m%d}.json"

def _read_cache(symbol: str) -> MarketSnapshot | None:
    path = _cache_key(symbol)
    if path.exists():
        data = json.loads(path.read_text())
        if datetime.now() - datetime.fromisoformat(data["cached_at"]) < CACHE_TTL:
            return MarketSnapshot(**data["snapshot"])
    return None

def _write_cache(symbol: str, snapshot: MarketSnapshot) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_key(symbol).write_text(json.dumps({
        "snapshot": dataclasses.asdict(snapshot),
        "cached_at": datetime.now().isoformat(),
    }))
```

### 4.2 准确率优化

| # | 优化项 | 当前状态 | 目标 | 方案 |
|---|--------|---------|------|------|
| **A1** | 情感词典扩充 | ~30个中英文词 | ~100个词 + 权重 | 收集财经新闻语料，统计高频情感词；给高确定性词（"制裁"、"创新高"）更高权重 |
| **A2** | 否定处理增强 | 3个token窗口 | 依存句法分析 | 使用 `jieba` 分词 + 简单的依存关系判断；或直接接LLM |
| **A3** | 新闻→标的映射 | 子串匹配 | 语义级匹配 | LLM 模式：`--llm` 时由模型判断"苹果发布MR头显"是否影响"纳指科技ETF" |
| **A4** | 决策矩阵校准 | 固定阈值 | 可配置 + 历史回测 | 用户可自定义阈值；Phase 3可加入历史数据回测最优阈值 |

#### A1 权重方案

```python
# 带权重的关键词
WEIGHTED_SENTIMENT = {
    # 高确定性 (权重 3)
    "制裁": (-3, "high"),
    "创新高": (+3, "high"),
    "退市": (-3, "high"),
    "破产": (-3, "high"),

    # 中确定性 (权重 2)
    "增长": (+2, "medium"),
    "下跌": (-2, "medium"),
    "合作": (+2, "medium"),

    # 低确定性 (权重 1)
    "预期": (+1, "low"),
    "调整": (-1, "low"),
}
```

### 4.3 可维护性优化

| # | 优化项 | 方案 |
|---|--------|------|
| **M1** | 配置外部化 | 抽取 `config.yaml`，所有阈值/关键词/新闻源可配置 |
| **M2** | 日志系统 | 替换 `print` 为 `logging` 模块，支持 `--debug` 输出详细日志 |
| **M3** | 插件化新闻源 | 定义 `NewsSource` 抽象基类，RSS/NewsAPI/WebScraping 各自实现 |
| **M4** | 类型检查 | 添加 `mypy` / `pyright` 到 CI，确保类型注解不退化 |

#### M3 抽象设计

```python
from abc import ABC, abstractmethod

class NewsSource(ABC):
    """Abstract news source."""

    @abstractmethod
    def fetch(self, keywords: list[str], limit: int) -> list[dict]:
        """Fetch news articles for given keywords."""

    @abstractmethod
    def name(self) -> str:
        """Human-readable source name."""


class GoogleNewsRSS(NewsSource):
    def fetch(self, keywords, limit):
        ...  # RSS 实现

class NewsAPISource(NewsSource):
    def fetch(self, keywords, limit):
        ...  # NewsAPI 实现

class MockNewsSource(NewsSource):
    def fetch(self, keywords, limit):
        ...  # Mock 实现
```

---

## 附录

### A. 依赖清单 (`requirements.txt`)

```
yfinance>=0.2.40
feedparser>=6.0.11
rich>=13.0.0
pyyaml>=6.0
requests>=2.31.0
```

### B. 开发依赖

```
pytest>=8.0.0
pytest-cov>=5.0.0
ruff>=0.5.0
```

### C. 配置参考 (`config.yaml` 完整结构)

```yaml
# stock_analyzer/config.yaml (Phase 2)
stocks:
  - symbol: "513100"
    aliases: ["纳指科技", "纳指科技ETF"]
    keywords: ["NVIDIA", "纳斯达克", "NASDAQ", "AI芯片", "GPU"]
  - symbol: "AAPL"

theme: "AI产业链"

analysis:
  thresholds:
    big_up: 3.0
    big_down: -3.0
    attention: 1.5
  sentiment:
    bullish_threshold: 0.3
    bearish_threshold: -0.3
    negation_window: 3      # 否定词向前搜索token数

news:
  sources:
    - type: rss
      url_template: "https://news.google.com/rss/search?q={keyword}&hl=zh-CN"
      max_per_keyword: 5
  max_total: 20
  cache_ttl_minutes: 15

output:
  formats: ["terminal", "markdown"]
  output_dir: "./reports"
```

---

> **文档版本**: v1.0  
> **日期**: 2026-06-21  
> **状态**: 待评审
