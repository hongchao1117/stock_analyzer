# 📊 Stock Analyzer — 多市场股票分析器

给定任意股票代码（A股/美股/港股），自动获取行情 + 新闻，生成**消息面摘要 + 操作建议**的每日简报。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 题目示例场景
python main.py --symbols 513100 513310 --theme "AI产业链"

# 跨市场混合分析
python main.py --symbols AAPL 600519 0700.HK

# 离线演示（使用内置 mock 数据）
python main.py --symbols 513100 NVDA TSLA --mock --verbose
```

## 支持的股票代码格式

| 市场 | 格式 | 示例 |
|------|------|------|
| A股（上交所） | 6位数字 60xxxx/51xxxx/68xxxx | `600519` `513100` `688981` |
| A股（深交所） | 6位数字 00xxxx/30xxxx | `000001` `300750` |
| 美股 | 1-5个字母 | `AAPL` `NVDA` `TSLA` |
| 港股 | 4-5位数字 | `0700` `9988` `00700` |
| 带后缀 | xxxx.HK / xxxx.SH / xxxx.SZ | `0700.HK` `300750.SZ` |

## 参数说明

```
--symbols, -s     股票代码列表（必填，支持多个）
--theme, -t       关注主题: AI产业链/新能源/半导体/消费/互联网/医药
--mock            强制使用内置 mock 数据（离线演示）
--output, -f      输出格式: terminal markdown json
--output-dir, -o  报告输出目录
--verbose, -v     显示被过滤的新闻详情
--debug           启用调试日志
```

## 项目结构

```
stock_analyzer/
├── main.py              # CLI入口 + Pipeline编排
├── models.py            # 共享数据结构
├── symbol_parser.py     # 代码格式识别 + 市场分类
├── mock_data.py         # 内置mock数据（3市场）
├── data/
│   ├── fetcher.py       # yfinance行情获取 + 降级
│   └── news_fetcher.py  # RSS新闻获取 + 去重
├── analysis/
│   ├── sentiment.py     # 中英双语情感分析引擎
│   └── advisor.py       # 二维决策矩阵建议生成
├── output/
│   └── reporter.py      # rich终端 + Markdown报告
├── PRD.md               # 产品设计文档
├── TDD.md               # 技术设计文档
└── README.md            # 本文件
```

## 架构特点

- **确定性多步流水线**: Parse → Fetch → Analyze → Output
- **容错降级**: 单只失败不影响全局；全部失败自动切 Mock
- **可解释**: 每条建议可追溯到具体新闻或行情数据
- **先规则后智能**: MVP用规则引擎100%跑通；`--llm` 接口预留

## 免责声明

⚠️ 本工具由AI生成，仅供学习参考，不构成投资建议。投资有风险，决策需谨慎。
