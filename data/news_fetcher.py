"""新闻获取 — 关键词构造 + RSS 获取 + 去重 + 降级.

使用 requests + xml.etree.ElementTree 解析 RSS（标准库，零额外依赖）。
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import datetime
from difflib import SequenceMatcher
from xml.etree import ElementTree

from models import StockInfo

logger = logging.getLogger(__name__)

# ---- 主题 → 关键词映射 ----
THEME_KEYWORDS: dict[str, list[str]] = {
    "AI产业链": [
        "人工智能", "AI芯片", "GPU", "大模型", "算力", "自动驾驶",
        "machine learning", "NVIDIA", "OpenAI", "HBM",
    ],
    "新能源": [
        "光伏", "锂电", "储能", "新能源汽车", "风电",
        "solar", "EV battery", "Tesla", "CATL", "比亚迪",
    ],
    "半导体": [
        "芯片", "晶圆", "光刻", "封装", "HBM", "EDA",
        "semiconductor", "TSMC", "ASML", "chip",
    ],
    "消费": ["白酒", "食品", "零售", "电商", "消费升级", "consumer", "retail", "e-commerce"],
    "互联网": ["互联网", "云计算", "SaaS", "社交媒体", "游戏", "cloud", "SaaS", "social media", "gaming"],
    "医药": ["医药", "创新药", "医疗器械", "CXO", "生物科技", "pharma", "biotech", "medical device", "FDA"],
}

_NAME_STOP_WORDS = {"etf", "指数", "基金", "联接", "LOF", "QDII", "A", "C"}


def build_keywords(
    stocks: list[StockInfo],
    theme: str | None = None,
    max_keywords: int = 20,
) -> list[str]:
    """构造新闻搜索关键词列表."""
    keywords: list[str] = []

    for stock in stocks:
        name = stock.name or stock.input_symbol
        parts = re.split(r"[\s\-·/]+", name)
        for part in parts:
            part = part.strip().rstrip(")")
            if not part or part.lower() in _NAME_STOP_WORDS:
                continue
            if len(part) >= 2:
                keywords.append(part)
        if stock.market == "US":
            keywords.append(stock.input_symbol)

    if theme:
        theme_clean = theme.strip()
        if theme_clean in THEME_KEYWORDS:
            keywords.extend(THEME_KEYWORDS[theme_clean])
        else:
            matched = False
            for preset, kws in THEME_KEYWORDS.items():
                if preset in theme_clean or theme_clean in preset:
                    keywords.extend(kws)
                    matched = True
                    break
            if not matched:
                keywords.append(theme_clean)

    # 去重保持顺序
    seen: set[str] = set()
    unique: list[str] = []
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower not in seen:
            seen.add(kw_lower)
            unique.append(kw)
    return unique[:max_keywords]


def build_rss_url(keyword: str, lang: str = "zh-CN") -> str:
    """构造 Google News RSS URL."""
    encoded = urllib.parse.quote(keyword)
    ceid_part = lang.split("-")[-1] if "-" in lang else lang
    return f"https://news.google.com/rss/search?q={encoded}&hl={lang}&ceid={lang}:{ceid_part}"


def _http_get_text(url: str, timeout: float = 10) -> str | None:
    """HTTP GET 请求，返回文本."""
    try:
        import requests
    except ImportError:
        logger.warning("requests 未安装，无法获取新闻")
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.debug("RSS 请求失败 %s: %s", url[:80], e)
        return None


def fetch_articles(keywords: list[str], max_per_keyword: int = 5) -> list[dict]:
    """从 RSS 获取新闻文章."""
    all_articles: list[dict] = []
    seen_urls: set[str] = set()

    for kw in keywords:
        try:
            url = build_rss_url(kw)
            xml_text = _http_get_text(url)
            if not xml_text:
                continue

            root = ElementTree.fromstring(xml_text)
            count = 0
            for item in root.iter("item"):
                title = ""
                link = ""
                source = ""
                pub_date = ""
                description = ""

                for child in item:
                    tag = child.tag.lower() if child.tag else ""
                    text = (child.text or "").strip()
                    if tag == "title":
                        title = text
                    elif tag == "link":
                        link = text
                    elif tag == "source":
                        source = text
                    elif tag == "pubdate":
                        pub_date = text
                    elif tag == "description":
                        description = text

                if not title or not link:
                    continue
                if link in seen_urls:
                    continue

                seen_urls.add(link)
                all_articles.append({
                    "title": _strip_html(title),
                    "summary": _strip_html(description)[:200],
                    "source": source,
                    "url": link,
                    "published": pub_date,
                    "search_keyword": kw,
                })
                count += 1
                if count >= max_per_keyword:
                    break
        except Exception as e:
            logger.debug("关键词 '%s' RSS 解析失败: %s", kw, e)
            continue

    return all_articles


def deduplicate(articles: list[dict], title_threshold: float = 0.85) -> list[dict]:
    """去重：URL 精确匹配 + 标题模糊匹配."""
    if not articles:
        return []

    result: list[dict] = []
    seen_urls: set[str] = set()
    seen_titles: list[str] = []

    for article in articles:
        url = article.get("url", "")
        title = article.get("title", "")

        if url and url in seen_urls:
            continue

        title_lower = title.lower()
        is_dup = any(
            _title_similarity(title_lower, t) >= title_threshold
            for t in seen_titles
        )
        if is_dup:
            continue

        if url:
            seen_urls.add(url)
        seen_titles.append(title_lower)
        result.append(article)

    return result


def fetch_all(
    stocks: list[StockInfo],
    theme: str | None = None,
    max_articles: int = 25,
) -> list[dict]:
    """新闻获取主入口."""
    keywords = build_keywords(stocks, theme)
    logger.info("搜索关键词 (%d个): %s", len(keywords), keywords[:10])

    articles = fetch_articles(keywords)
    logger.info("获取到 %d 条原始新闻", len(articles))

    articles = deduplicate(articles)
    logger.info("去重后 %d 条", len(articles))

    articles.sort(key=lambda a: a.get("published", ""), reverse=True)
    return articles[:max_articles]


# ---- 工具函数 ----

_HTML_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """去除 HTML 标签和实体."""
    text = _HTML_RE.sub("", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return text.strip()


def _title_similarity(a: str, b: str) -> float:
    """标题相似度."""
    if a == b:
        return 1.0
    if len(a) < 20 or len(b) < 20:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()
