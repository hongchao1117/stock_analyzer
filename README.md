# 📊 Stock Analyzer — AI Agent 驱动的多市场股票分析器

> AI Agent 自主搜索真实新闻、分析行情、生成操作建议。支持自然语言输入。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 交互模式（推荐）
python main.py

# CLI 模式
python main.py -s AAPL 600519 0700.HK -t "AI芯片"

# 自然语言输入
python main.py
👉 我持仓纳指科技ETF、中韩半导体ETF，还有美股SOXL
👉 关注方向: 半导体
```

## 两种输入方式

| 方式 | 示例 |
|------|------|
| **股票代码** | `600519 AAPL 0700.HK SOXL` |
| **自然语言** | `我目前的持仓是纳指科技ETF、中韩半导体ETF、美股SOXL` |

## AI Agent 工作流程

```
用户输入 → Agent 自主决策:

  Step 0: parse_portfolio      (自然语言时) 解析持仓 → 提取股票代码
  Step 1: fetch_market_quotes  新浪财经 → 实时行情（价格/涨跌幅/成交量）
  Step 2: analyze_stock_news   搜索真实新闻 → DeepSeek 情感分析
  Step 3: generate_trading_advice  综合行情+消息面 → 操作建议
  Step 4: submit_final_report  提交报告
```

Agent 会根据涨跌幅自适应：波动大→深挖原因，波动小→常规分析。同一只股票不同主题会产生不同建议。

## 支持的股票代码

| 市场 | 格式 | 示例 |
|------|------|------|
| A股 | 6位数字 | `600519` `513100` `000001` |
| 美股 | 纯字母 | `AAPL` `NVDA` `SOXL` |
| 港股 | 4-5位数字 | `0700` `9988` `0700.HK` |

## 参数说明

```
--symbols, -s     股票代码列表（不传则进入交互模式）
--theme, -t       关注方向，自由文本（如 "AI芯片"、"消费复苏"）
--api-key         DeepSeek API Key（首次输入后自动保存）
--output, -f      输出格式: terminal markdown json（默认: terminal markdown）
--output-dir, -o  报告输出目录（默认: output/）
--verbose, -v     显示详细信息
--debug           启用调试日志
```

## 项目结构

```
stock_analyzer/
├── main.py              # CLI入口 + Agent启动
├── agent.py             # ReAct Agent 核心循环
├── tools.py             # 5个Agent工具定义与实现
├── llm.py               # DeepSeek API 封装（completion + function calling）
├── models.py            # 共享数据结构 + AgentState
├── symbol_parser.py     # 股票代码识别 + 市场分类
├── data/
│   └── fetcher.py       # 新浪财经实时行情（A股/美股/港股）
├── output/
│   └── reporter.py      # rich终端 + Markdown报告
├── PRD.md               # 产品设计文档
├── TDD.md               # 技术设计文档
└── README.md            # 本文件
```

## 架构特点

- **🤖 AI Agent 自主决策**: ReAct 循环（Think → Act → Observe），非固定流水线
- **📰 真实新闻搜索**: Bing News + 百度新闻，返回真实可点击链接
- **💬 自然语言理解**: 支持"我持仓xxx"式输入，自动解析
- **🔧 5个可组合工具**: Agent 自主选择调用时机和参数
- **🛡️ 容错降级**: 单只失败不影响全局；搜索无结果时 LLM 兜底
- **🔑 API Key 持久化**: 首次输入后自动保存，无需重复配置

## Agent 工具集

| 工具 | 用途 |
|------|------|
| `parse_portfolio` | 自然语言 → 股票代码 |
| `fetch_market_quotes` | 新浪财经实时行情 |
| `analyze_stock_news` | 搜索真实新闻 + DeepSeek 情感分析 |
| `generate_trading_advice` | 综合行情+消息面 → 操作建议 |
| `submit_final_report` | 提交最终报告 |

## 免责声明

⚠️ 本工具由 AI Agent 自主生成分析，仅供学习参考，不构成投资建议。投资有风险，决策需谨慎。
