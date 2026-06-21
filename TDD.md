# TDD — 股票分析器：AI Agent 技术设计文档

---

## 目录

- [1. High Level Design](#1-high-level-design)
  - [1.1 系统架构概览](#11-系统架构概览)
  - [1.2 技术选型](#12-技术选型)
  - [1.3 Agent 循环设计](#13-agent-循环设计)
  - [1.4 数据流](#14-数据流)
  - [1.5 模块划分与职责](#15-模块划分与职责)
  - [1.6 错误处理策略](#16-错误处理策略)
- [2. Low Level Design](#2-low-level-design)
  - [2.1 `agent.py` — ReAct Agent 核心](#21-agentpy--react-agent-核心)
  - [2.2 `tools.py` — 工具定义与实现](#22-toolspy--工具定义与实现)
  - [2.3 `llm.py` — DeepSeek 集成](#23-llmpy--deepseek-集成)
  - [2.4 `data/fetcher.py` — 新浪财经行情](#24-datafetcherpy--新浪财经行情)
  - [2.5 `symbol_parser.py` — 代码解析](#25-symbol_parserpy--代码解析)
  - [2.6 `output/reporter.py` — 报告生成](#26-outputreporterpy--报告生成)
  - [2.7 `models.py` — 数据模型](#27-modelspy--数据模型)
  - [2.8 `main.py` — CLI 入口](#28-mainpy--cli-入口)
- [3. 测试策略](#3-测试策略)
- [4. 优化路径](#4-优化路径)

---

## 1. High Level Design

### 1.1 系统架构概览

```
                          main.py (Agent Launcher)
 ┌──────────────────────────────────────────────────────────────┐
 │                                                               │
 │  User Input ──▶ agent.run_agent() ──▶ output/reporter.render()│
 │                     │                          ▲              │
 │                     │ ReAct Loop               │              │
 │                     ▼                          │              │
 │           ┌─────────────────┐       ┌──────────────────┐     │
 │           │  DeepSeek API   │       │  DailyBriefing   │     │
 │           │  function call  │──▶    │  (累积状态)      │     │
 │           └─────────────────┘       └──────────────────┘     │
 │                     │                          ▲              │
 │                     │ tool_calls               │              │
 │                     ▼                          │              │
 │           ┌─────────────────┐                  │              │
 │           │  tools.py       │──────────────────┘              │
 │           │  dispatch_tool()│  写入 state                     │
 │           └─────────────────┘                                 │
 │                     │                                          │
 │         ┌───────────┼───────────┬──────────┐                  │
 │         ▼           ▼           ▼          ▼                  │
 │    parse_     fetch_     analyze_    generate_                │
 │    portfolio  market     stock_news  trading_                 │
 │              (新浪财经)   (DeepSeek)  advice(DeepSeek)        │
 │                                                                │
 └──────────────────────────────────────────────────────────────┘
```

**架构模式**: ReAct Agent（Reasoning + Acting），非固定流水线。

**核心思想**: Agent 接收任务后，自主决定调用哪些工具、何时调用、调用多少次，直到信息足够生成报告。

### 1.2 技术选型

| 层级 | 技术 | 选型理由 |
|------|------|---------|
| Agent 引擎 | DeepSeek Chat API (`deepseek-chat`) | OpenAI 兼容 function calling，中文能力强 |
| 行情数据 | 新浪财经 HTTP API (`hq.sinajs.cn`) | 免费、覆盖 A股/美股/港股、无需 API Key |
| HTTP 客户端 | `requests` | 新浪 + DeepSeek 统一使用 |
| 终端渲染 | `rich` ≥13.0 | 彩色表格/面板/Panel/Markdown |
| 配置 | `pyyaml` ≥6.0 | 可选配置文件 |
| 运行时 | Python ≥3.11 | `Self` 类型等新特性 |

**不引入的依赖**: yfinance（被墙）、feedparser（用 DeepSeek 替代 RSS）、pandas/numpy（太重）

### 1.3 Agent 循环设计

```
run_agent(raw_symbols, theme, api_key) → DailyBriefing

┌─────────────────────────────────────────────────────┐
│  System Prompt (工具列表 + 工作流程)                 │
│  User Task (股票代码 + 主题)                         │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
         ┌──────────────────────┐
         │  step < MAX_STEPS(8)? │──No──▶ fallback briefing
         └──────────┬───────────┘
                    │ Yes
                    ▼
         ┌──────────────────────┐
         │  DeepSeek API Call    │
         │  (messages + tools)   │
         └──────────┬───────────┘
                    │
          ┌─────────┴──────────┐
          ▼                    ▼
    有 tool_calls         只有 content
          │                    │
          ▼                    ▼
  执行每个 tool      追加 assistant msg
  结果追加 tool msg   提示 Agent 继续
          │                    │
          ▼                    ▼
   submit_final_report?   回到循环
          │
          ▼
   _build_briefing_from_state()
   从 state 中读取累积数据
```

**关键设计决策**:

| 决策 | 选择 | 理由 |
|------|------|------|
| State 由工具直接写入 | `state.news_items.append()` | 避免事后从日志解析 JSON |
| max_steps=8 | Pre-flight 检查 | 防止无限循环，在调用前截断 |
| 工具异常不崩溃 | try/catch → 返回 error JSON | Agent 可看到错误并调整策略 |
| submit_final_report 结束 | 检查 tool_name | 明确的终止信号 |

### 1.4 数据流

```
User Input (自然语言 or 代码)
    │
    ▼
main.py: 判断输入类型
    │
    ├─ 纯代码 → parse_symbols 预校验
    └─ 自然语言 → 直接传给 Agent
    │
    ▼
agent.py: 启动 ReAct 循环
    │
    ├─ Step 0: parse_portfolio (自然语言时)
    │     DeepSeek 解析 → 提取 raw_symbols
    │
    ├─ Step 1: fetch_market_quotes
    │     symbol_parser + data/fetcher → MarketSnapshot[]
    │     写入 state.snapshots
    │
    ├─ Step 2-N: analyze_stock_news × 每只股票
    │     DeepSeek → NewsItem[]
    │     写入 state.news_items
    │
    ├─ Step N+1: generate_trading_advice × 每只股票
    │     DeepSeek → {action, confidence, reasons, risk_note}
    │     写入 state.advice_data
    │
    └─ Step Last: submit_final_report
          state.submitted = True
    │
    ▼
_build_briefing_from_state()
    从 state 组装 DailyBriefing
    │
    ▼
output/reporter.render()
    → rich 终端 + Markdown 文件
```

### 1.5 模块划分与职责

```
stock_analyzer/
├── main.py              # CLI入口 + Agent启动 + 输出调度
├── agent.py             # ReAct Agent 核心循环
├── tools.py             # 5个工具的定义(JSON Schema) + 实现
├── llm.py               # DeepSeek API 封装 (completion + function call)
├── models.py            # 所有 dataclass + AgentState
├── symbol_parser.py     # 股票代码识别 + 标准化
├── data/
│   └── fetcher.py       # 新浪财经行情获取 (CN/US/HK)
├── analysis/            # 保留: 规则引擎 (未被Agent使用)
│   ├── sentiment.py
│   └── advisor.py
├── output/
│   └── reporter.py      # 终端 rich + Markdown + JSON 渲染
└── requirements.txt
```

| 模块 | 职责 | 是否调用外部API |
|------|------|:---:|
| `agent.py` | ReAct 循环、状态管理、简报构建 | 否 |
| `tools.py` | 工具 Schema + 实现、dispatch | 是 (DeepSeek) |
| `llm.py` | DeepSeek completion / function call | 是 |
| `data/fetcher.py` | 新浪财经行情 | 是 (hq.sinajs.cn) |
| `symbol_parser.py` | 代码格式识别 | 否 |
| `output/reporter.py` | 终端渲染 + 写文件 | 否 |
| `models.py` | 8 个 dataclass + 常量 | 否 |
| `main.py` | CLI、输入判断、API Key 管理 | 否 |

### 1.6 错误处理策略

```
Agent 层级:
  ├─ DeepSeek API 失败 → 返回 error briefing
  ├─ 工具执行异常 → try/catch, 返回 error JSON 给 Agent
  ├─ 工具参数 JSON 解析失败 → 返回空 dict, 继续
  ├─ 达到 max_steps → 构建 fallback briefing
  └─ Agent 空响应 → 追加提示, 继续循环

数据层级:
  ├─ 新浪某只股票失败 → 返回 None, 不影响其他
  ├─ 全部行情失败 → state.snapshots 全 None → error briefing
  └─ 解析错误 → parse_errors 收集, 不阻塞

原则:
  1. 永不崩溃 — 每条路径都有兜底
  2. 降级透明 — data_status_label 反映真实状态
  3. 单点不影响全局
```

---

## 2. Low Level Design

### 2.1 `agent.py` — ReAct Agent 核心

#### 系统提示词

Agent 被赋予清晰的工作流程指令：判断输入类型 → 获取行情 → 分析新闻 → 生成建议 → 提交报告。提示词中明确要求：
- 自然语言输入先调用 `parse_portfolio`
- 大涨/大跌（>2%）优先分析原因
- 用户指定主题时从该角度切入
- 完成后必须调用 `submit_final_report`

#### 核心循环

```python
def run_agent(
    raw_symbols: list[str],
    theme: str | None = None,
    api_key: str | None = None,
    verbose: bool = False,
) -> DailyBriefing:
    state = AgentState()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_task},
    ]

    while state.step < MAX_STEPS:  # Pre-flight check
        state.step += 1
        response = call_deepseek_agent(messages, tools=TOOL_DEFINITIONS, api_key=api_key)

        if response is None:
            return fallback_briefing  # API 完全失败

        if response["tool_calls"]:
            # 执行工具 → 追加 assistant + tool 消息
            for tc in tool_calls:
                observation = dispatch_tool(name, args, state, api_key)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": observation})

            if tool_name == "submit_final_report":
                return _build_briefing_from_state(state)

        elif response["content"]:
            # 纯文本响应 → 追加提示继续
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": "请继续分析..."})

    return fallback_briefing  # 达到最大步数
```

#### 简报构建

```python
def _build_briefing_from_state(state, raw_symbols, date_str, theme):
    # 从 state.advice_data 构建 StockAdvice 列表
    for stock, snap in zip(state.stocks, state.snapshots):
        ad = state.advice_data.get(stock.normalized_symbol)
        if ad:
            advice.append(StockAdvice(
                action=ad["action"], confidence=ad["confidence"],
                reasons=ad["reasons"], risk_note=ad.get("risk_note"),
                ...
            ))
        else:
            advice.append(default_advice)  # Agent 未覆盖的

    return DailyBriefing(
        snapshots=[s for s in state.snapshots if s is not None],
        news_items=state.news_items,  # 工具直接填充
        advice=advice,
        ...
    )
```

### 2.2 `tools.py` — 工具定义与实现

#### Tool Schema（OpenAI function-calling 格式）

5 个工具，每个包含 `name`、`description`（含使用时机）、`parameters`（JSON Schema）。

**关键设计**:
- `description` 中说明"何时使用"，帮助 Agent 正确选择
- `parameters` 中 `required` 字段明确，避免 Agent 遗漏
- 工具之间独立，可任意顺序调用

#### 工具实现

**parse_portfolio**: DeepSeek 子调用，prompt 中含已知 ETF 映射表（纳指科技ETF→513100，中韩半导体→513310 等10+条），未知名称由 LLM 推断。

**fetch_market_quotes**: 封装 `symbol_parser.parse_symbols()` + `data.fetcher.fetch_all()`，写入 `state.stocks` + `state.snapshots`。

**analyze_stock_news**: DeepSeek 子调用生成 2-3 条新闻，每条自动生成百度搜索链接 (`baidu.com/s?wd=标题`)，直接 `state.news_items.append(NewsItem(...))`。

**generate_trading_advice**: DeepSeek 子调用，综合 `findings_summary` 生成建议，写入 `state.advice_data[symbol]`。

**submit_final_report**: 设置 `state.submitted = True`，Agent 循环检测后退出。

#### Tool Dispatch

```python
def dispatch_tool(tool_name, tool_args, state, api_key) -> str:
    # try/catch 包裹每个工具
    # 结果记录到 state.tool_log
    # 返回 JSON 字符串给 Agent
```

### 2.3 `llm.py` — DeepSeek 集成

#### 双模式 API

```python
# 模式1: 纯 Completion（旧 pipeline + 工具内部子调用）
_call_deepseek(prompt, api_key) -> dict | None

# 模式2: Function Calling（Agent 主循环）
call_deepseek_agent(messages, tools, api_key) -> {
    "content": str | None,
    "tool_calls": [{"id", "function": {"name", "arguments"}}] | None
}
```

#### API Key 加载链

```
--api-key 参数 > DEEPSEEK_API_KEY 环境变量 > .deepseek_key 文件
```

#### 响应处理

- 自动剥离 markdown 代码块（```json ... ```）
- JSON 解析失败返回 None（不抛异常）
- Agent 模式支持 `tool_choice: "auto"`

### 2.4 `data/fetcher.py` — 新浪财经行情

#### API 端点

```
A股: http://hq.sinajs.cn/list=sh600519 或 sz000001
美股: http://hq.sinajs.cn/list=gb_aapl
港股: http://hq.sinajs.cn/list=hk00700 (5位补零)
```

#### 符号转换

```python
yfinance格式 → 新浪格式:
  600519.SS → sh600519
  000001.SZ → sz000001
  AAPL      → gb_aapl
  0700.HK    → hk00700  (关键: 5位补零)
```

#### 解析器（三个市场独立）

| 市场 | 关键字段位置 | 特殊处理 |
|------|-------------|---------|
| A股 | name[0], price[3], prev_close[2], volume[8]×100 | **涨跌幅手动计算**: (price-prev_close)/prev_close |
| 美股 | name[0], price[1], change_pct[2], volume[10] | change_pct 直接可用 |
| 港股 | cn_name[1], price[2], prev_close[6], change_pct[8], volume[12] | change_pct 直接可用 |

#### 编码处理

新浪返回 GBK → 尝试 GBK 解码 → 失败则 latin-1 兜底。

### 2.5 `symbol_parser.py` — 代码解析

#### 识别规则

```
含 "." → 解析后缀 (.HK/.SH/.SZ)
6位数字 → A股 (60/51/68→.SS, 00/30→.SZ)
4-5位数字 → 港股 (补零→.HK)
纯字母 → 美股 (原样)
其他 → SymbolParseError
```

### 2.6 `output/reporter.py` — 报告生成

#### 三种输出格式

| 格式 | 实现 | 特点 |
|------|------|------|
| Terminal | rich Table/Panel | 新闻标题可点击 `[link=URL]` |
| Markdown | 模板 + 文件 | 标题 `[text](url)` 可点击 |
| JSON | dataclasses.asdict | briefing.json |

#### Markdown 模板结构

```
📊 每日投资简报 (日期/数据状态/主题/免责声明)
📈 行情快照 (表格)
📰 关键消息 (按标的分组，含情感统计)
💡 操作建议 (表格)
📋 被过滤的新闻
```

### 2.7 `models.py` — 数据模型

#### 8 个 Dataclass

```
StockInfo          — 解析后的股票信息
MarketSnapshot     — 实时行情快照
NewsItem           — 带情感的新闻条目
StockAdvice        — 操作建议
DailyBriefing      — 每日简报（顶层容器）
AgentState         — Agent 运行时状态
Thresholds         — (保留) 决策矩阵阈值
```

#### AgentState 详解

```python
@dataclass
class AgentState:
    step: int = 0                                    # 当前步数
    observations: list[str]                          # 工具返回摘要
    tool_log: list[dict]                             # {step, tool, args, result_summary}
    stocks: list[StockInfo]                          # 解析后的股票
    snapshots: list[MarketSnapshot | None]           # 行情快照
    news_items: list[NewsItem]                       # 工具直接填充
    advice_data: dict[str, dict]                     # symbol → {action, confidence, ...}
    submitted: bool = False                          # 是否已提交报告
```

### 2.8 `main.py` — CLI 入口

#### 两种模式

**交互模式** (`python main.py`): 提示输入 → 自然语言/代码判断 → 可选主题 → Agent 分析

**CLI模式** (`python main.py -s AAPL 600519 -t "AI"`): 直接启动 Agent

#### 输入类型判断

```python
is_natural = any(not re.match(r'^[a-zA-Z0-9.]+$', s) for s in raw_symbols)
if not is_natural:
    parse_symbols()  # 预校验
else:
    # 原样传给 Agent，由 parse_portfolio 处理
```

#### API Key 持久化

```
.save → .deepseek_key (chmod 600)
.load → --api-key > env DEEPSEEK_API_KEY > .deepseek_key
```

---

## 3. 测试策略

### 3.1 测试金字塔

```
         ┌─────────┐
         │  E2E    │  全链路: 自然语言输入 → Agent 分析 → 报告
         │  2 tests│
        ┌┴─────────┴┐
        │Integration│  Agent + 工具协作、实时行情、DeepSeek 联通
        │  4 tests  │
       ┌┴───────────┴┐
       │    Unit      │  各模块核心函数 + 边界
       │  ~15 tests   │
      ┌┴──────────────┴┐
      │   Import check  │  python -c "import tools, agent, main"
      └────────────────┘
```

### 3.2 关键测试场景

| # | 场景 | 验证点 |
|---|------|--------|
| T1 | 自然语言输入 | parse_portfolio 正确解析 ETF 名称 |
| T2 | 代码输入 | 直接 fetch_market_quotes |
| T3 | 主题影响 | 同股票不同主题 → 不同建议 |
| T4 | 部分失败 | 一只股票代码错误 → 其他正常 |
| T5 | Agent 不超步数 | steps ≤ 8 |
| T6 | Markdown 链接 | report.md 含 baidu.com/s?wd= |
| T7 | API Key 持久化 | .deepseek_key 自动加载 |

---

## 4. 优化路径

### 4.1 性能

| # | 优化项 | 方案 |
|---|--------|------|
| P1 | 并发工具调用 | Agent 可同时调用 analyze_stock_news × N |
| P2 | 行情缓存 | 5分钟 TTL 本地文件缓存 |
| P3 | 流式输出 | DeepSeek streaming，边分析边展示 |

### 4.2 准确率

| # | 优化项 | 方案 |
|---|--------|------|
| A1 | 真实新闻搜索 | 接入 Bing/NewsAPI 替代 LLM 生成 |
| A2 | 多源交叉验证 | 新浪 + 备用数据源 |
| A3 | 历史对比 | 记录每日建议，回测准确率 |

### 4.3 Agent 能力

| # | 优化项 | 方案 |
|---|--------|------|
| C1 | 用户交互 | Agent 可向用户提问（"SOXL波动极大，是否调整仓位？"） |
| C2 | 记忆 | 跨会话记住用户持仓偏好 |
| C3 | 多 Agent 协作 | 分工：一只 Agent 负责行情，一只负责新闻，一只负责建议 |

---

> **文档版本**: v3.0  
> **日期**: 2026-06-21  
> **状态**: 已实现 — 从 Pipeline 架构重构为 ReAct Agent 架构
