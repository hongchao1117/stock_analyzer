#!/usr/bin/env python3
"""股票分析器 CLI 入口 — 真实行情 + DeepSeek LLM 分析.

用法:
  python main.py                          # 交互模式
  python main.py -s AAPL 600519 0700.HK   # 命令行模式

数据源: 新浪财经 (A股/美股/港股)
分析引擎: DeepSeek Chat API (DEEPSEEK_API_KEY 环境变量)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from symbol_parser import parse_symbols
from models import DailyBriefing, StockInfo, MarketSnapshot, NewsItem, StockAdvice
from data.fetcher import fetch_all as fetch_market, all_failed
from llm import analyze as llm_analyze
from output.reporter import render

logger = logging.getLogger(__name__)

# 项目根目录（无论从哪里执行，输出路径始终固定）
PROJECT_DIR = Path(__file__).resolve().parent

PRESET_THEMES = ["AI产业链", "新能源", "半导体", "消费", "互联网", "医药"]

# API Key 持久化文件
_KEY_FILE = PROJECT_DIR / ".deepseek_key"


def _load_api_key(cli_key: str | None = None) -> str | None:
    """加载 DeepSeek API Key：CLI 参数 > 环境变量 > 本地文件."""
    if cli_key:
        return cli_key
    env_key = os.environ.get("DEEPSEEK_API_KEY")
    if env_key:
        return env_key
    try:
        if _KEY_FILE.exists():
            return _KEY_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return None


def _save_api_key(key: str) -> None:
    """将 API Key 持久化到本地文件."""
    try:
        _KEY_FILE.write_text(key, encoding="utf-8")
        _KEY_FILE.chmod(0o600)  # 仅 owner 可读写
    except Exception:
        pass  # 非关键路径


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器."""
    parser = argparse.ArgumentParser(
        prog="stock-analyzer",
        description="多市场股票分析器 — 真实行情 + DeepSeek AI 分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                          # 交互模式
  python main.py -s AAPL NVDA 600519      # 命令行模式
  python main.py -s AAPL 0700.HK -t "AI产业链"
        """,
    )
    parser.add_argument(
        "--symbols", "-s", nargs="+", default=None,
        help="股票代码列表（不传则进入交互模式）",
    )
    parser.add_argument(
        "--theme", "-t", default=None,
        help=f"关注主题，预置: {', '.join(PRESET_THEMES)}。也支持自定义。",
    )
    parser.add_argument(
        "--api-key", default=None,
        help="DeepSeek API Key（优先于环境变量 DEEPSEEK_API_KEY）",
    )
    parser.add_argument(
        "--output-dir", "-o", type=Path, default=PROJECT_DIR / "output",
        help=f"报告输出目录 (默认: {PROJECT_DIR / 'output'})",
    )
    parser.add_argument(
        "--output", "-f", choices=["terminal", "markdown", "json"],
        default=["terminal", "markdown"], nargs="+",
        help="输出格式 (默认: terminal markdown)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="显示详细信息",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="启用 DEBUG 日志",
    )
    return parser


# ═══════════════════════════════════════════════
# 交互模式
# ═══════════════════════════════════════════════

def _interactive_input() -> tuple[list[str], str | None]:
    """交互式获取用户输入."""
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║       📊 Stock Analyzer — 股票分析器         ║")
    print("║       DeepSeek AI 驱动 · 真实行情             ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print("支持: A股(600519)  美股(AAPL)  港股(0700/0700.HK)")
    print("多只用空格分隔: 600519 AAPL 0700.HK")
    print(f"预置主题: {', '.join(PRESET_THEMES)}")
    print()

    while True:
        try:
            raw = input("👉 股票代码: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            sys.exit(0)
        if raw:
            symbols = [s.strip() for s in raw.split() if s.strip()]
            if symbols:
                break
        print("⚠️  请输入至少一个股票代码。")

    try:
        theme = input("👉 关注主题（回车跳过）: ").strip()
    except (EOFError, KeyboardInterrupt):
        theme = None
    if not theme:
        theme = None

    return symbols, theme


# ═══════════════════════════════════════════════
# Pipeline
# ═══════════════════════════════════════════════

def run_pipeline(
    raw_symbols: list[str],
    theme: str | None = None,
    api_key: str | None = None,
    output_dir: Path = Path("output"),
    output_formats: list[str] | None = None,
    verbose: bool = False,
) -> DailyBriefing:
    """执行完整分析流水线."""
    if output_formats is None:
        output_formats = ["terminal", "markdown"]

    date_str = datetime.now().strftime("%Y-%m-%d")
    errors: list[str] = []

    # ═══ Step 1: 解析代码 ═══
    stocks, parse_errors = parse_symbols(raw_symbols)
    errors.extend(parse_errors)
    if not stocks:
        return DailyBriefing(
            date=date_str,
            disclaimer="本报告由AI生成，仅供参考，不构成投资建议。",
            data_status="error",
            data_status_label="全部代码解析失败",
            errors=errors,
        )
    logger.info("解析成功 %d 只: %s", len(stocks), [s.normalized_symbol for s in stocks])

    # ═══ Step 2: 获取行情（新浪财经） ═══
    logger.info("获取实时行情...")
    snapshots = fetch_market(stocks)

    failed_snapshots = sum(1 for s in snapshots if s is None)
    snapshots_clean: list[MarketSnapshot | None] = snapshots

    if all_failed(snapshots):
        errors.append("所有股票行情获取失败，请检查网络连接")
        return DailyBriefing(
            date=date_str,
            disclaimer="本报告由AI生成，仅供参考，不构成投资建议。",
            data_status="error",
            data_status_label="行情获取失败",
            errors=errors,
        )

    data_status = "live"
    data_status_label = "实时数据 · 新浪财经"
    if failed_snapshots > 0:
        data_status = "partial"
        data_status_label = f"实时数据 · 新浪财经（{failed_snapshots}只失败）"

    # 给没有名称的股票补充名称
    for i, stock in enumerate(stocks):
        snap = snapshots[i] if i < len(snapshots) else None
        if snap and snap.name == snap.symbol and stock.name:
            snap.name = stock.name

    logger.info("行情获取完成: %d 成功, %d 失败",
                len(stocks) - failed_snapshots, failed_snapshots)

    # ═══ Step 3: DeepSeek LLM 分析 ═══
    logger.info("调用 DeepSeek 分析...")
    news_items, advice, llm_error = llm_analyze(stocks, snapshots_clean, theme, api_key)

    if llm_error:
        errors.append(llm_error)

    # ═══ Step 4: 组装简报 ═══
    briefing = DailyBriefing(
        date=date_str,
        disclaimer="⚠️ 本报告由 DeepSeek AI 生成，仅供参考，不构成投资建议。投资有风险，决策需谨慎。",
        data_status=data_status,
        data_status_label=data_status_label,
        snapshots=[s for s in snapshots_clean if s is not None],
        news_items=news_items,
        advice=advice,
        dropped_news=[{"reason": e} for e in errors],
        errors=errors,
        theme=theme,
    )

    # ═══ Step 5: 渲染输出 ═══
    results = render(briefing, output_dir=output_dir, formats=output_formats, verbose=verbose)
    for fmt, path in results.items():
        if path:
            logger.info("已输出 %s → %s", fmt, path)

    return briefing


# ═══════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════

def main() -> None:
    parser = build_parser()
    args_has_symbols = any(arg in sys.argv for arg in ("--symbols", "-s"))

    if not args_has_symbols:
        known_args, _ = parser.parse_known_args()
        log_level = logging.DEBUG if known_args.debug else (
            logging.INFO if known_args.verbose else logging.WARNING
        )
        logging.basicConfig(level=log_level, format="%(levelname)s [%(name)s] %(message)s")

        api_key = _load_api_key(known_args.api_key)
        raw_symbols, theme = _interactive_input()
        if known_args.theme:
            theme = known_args.theme

        # 首次使用提示输入 API Key
        if not api_key:
            print()
            print("🔑 未检测到 DeepSeek API Key。")
            print("   获取地址: https://platform.deepseek.com/api_keys")
            try:
                key_input = input("👉 请输入 API Key（回车跳过）: ").strip()
            except (EOFError, KeyboardInterrupt):
                key_input = ""
            if key_input:
                api_key = key_input
                _save_api_key(key_input)
                print("✅ API Key 已保存，下次自动使用。")
            else:
                print("⚠️  跳过，将不生成 AI 分析。")

        try:
            run_pipeline(
                raw_symbols=raw_symbols, theme=theme,
                api_key=api_key,
                output_dir=known_args.output_dir,
                output_formats=known_args.output,
                verbose=known_args.verbose,
            )
        except KeyboardInterrupt:
            print("\n已中断", file=sys.stderr)
            sys.exit(130)
        except Exception as e:
            logger.exception("致命错误: %s", e)
            print(f"❌ 运行失败: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        args = parser.parse_args()
        log_level = logging.DEBUG if args.debug else (
            logging.INFO if args.verbose else logging.WARNING
        )
        logging.basicConfig(level=log_level, format="%(levelname)s [%(name)s] %(message)s")

        api_key = _load_api_key(args.api_key)
        # 如果通过 --api-key 传入，自动持久化
        if args.api_key and not _KEY_FILE.exists():
            _save_api_key(args.api_key)

        try:
            run_pipeline(
                raw_symbols=args.symbols, theme=args.theme,
                api_key=api_key,
                output_dir=args.output_dir,
                output_formats=args.output,
                verbose=args.verbose,
            )
        except KeyboardInterrupt:
            print("\n已中断", file=sys.stderr)
            sys.exit(130)
        except Exception as e:
            logger.exception("致命错误: %s", e)
            print(f"❌ 运行失败: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
