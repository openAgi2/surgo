# A-share 数据层移植计划

目标：把 surgo 引擎的默认数据源从美股 vendor（SEC EDGAR / FRED / StockTwits 等）
扩展到 **A 股**，数据源用 Tushare / AKShare / BaoStock。

原则：**只做加法**。保留原版的 point-in-time 完整性、防未来函数回测、vendor
注册表机制；A 股适配作为新的 vendor 实现注册进去，不破坏引擎的既有契约。

只从 TradingAgents-CN 的 **Apache-2.0** 组件（其 `tradingagents/` 目录）移植；
不触碰其专有的 `app/` / `frontend/` / `core/`。

## 背景：两个底座各自有什么

| 能力 | 原版 TradingAgents | TradingAgents-CN（Apache 引擎） |
|---|---|---|
| 引擎 | 干净、自包含、可运行 | 耦合专有层（25 处 import app/core），不可直接运行 |
| 数据 vendor | alpha_vantage / yahoo / sec_edgar / fred / reddit / stocktwits / polymarket | tushare / akshare / baostock + 中文财经新闻 |
| A 股分析师 | 无 | china_market / index / sector / social_media 等 |
| 工程严谨性 | point-in-time、防未来函数回测、vendor 注册表 | 较弱 |

## 移植路线（建议按序）

### M1 — A 股行情 vendor
- [ ] 研究原版 vendor 抽象：`tradingagents/dataflows/vendors/`（`router.py` / `base`）
- [ ] 从 CN `tradingagents/dataflows/` 提取 tushare/akshare/baostock 的行情获取逻辑
  （日线、实时快照、指数、板块），剥离其对 `app/`/`core/` 的依赖
- [ ] 在 surgo 引擎内实现为新的 vendor 模块：`tradingagents/dataflows/vendors/ashare/`
  - [ ] `tushare_client.py`（日线/财务/基本面）
  - [ ] `akshare_client.py`（实时/新闻/板块）
  - [ ] `baostock_client.py`（历史行情备选）
- [ ] 接入原版 vendor 注册表，使 `--ticker 600519` 走 A 股 vendor
- [ ] 依赖：在 `pyproject.toml` 增加 `tushare` / `akshare` / `baostock`

### M2 — A 股代码与交易日历
- [ ] A 股代码识别与归一化（`600519.SH` / `000001.SZ` / 6 位简码）
- [ ] A 股交易日历（用于 point-in-time 与回测网格，替换原版美股日历假设）

### M3 — A 股基本面与财务
- [ ] 财务三表 / 主要指标（替代 SEC EDGAR 路径）
- [ ] 保留原版的「as-filed / point-in-time」语义：按分析日期只取当时已披露的财报

### M4 — A 股特色分析师（可选增强）
- [ ] 大盘分析师（index analyst）
- [ ] 板块分析师（sector analyst）
- [ ] 中文社媒/舆情分析师（替代 StockTwits/Reddit 路径）
- 参考 CN `tradingagents/agents/analysts/`，但重写成挂到 surgo 引擎的干净实现

### M5 — 中文财经新闻
- [ ] 从 CN `tradingagents/dataflows/news/chinese_finance.py` 等提取中文新闻源
- [ ] 接入 news analyst 工具链

## 验收标准（每个 milestone）

- 引擎可运行：`surgo --ticker 600519 --date <D>` 产出完整研究报告
- point-in-time：分析日期 D 的报告只引用 D 当日及之前可得的数据（无未来函数）
- 回测网格在 A 股标的上可跑通并聚合评分
- 全部新代码 Apache-2.0，NOTICE 保持双血统声明

## 明确不做

- 不引入 TradingAgents-CN 的 `app/` / `frontend/` / `core/`（专有许可）
- 不实现其 Pro 功能的代码（Agent 工坊、定时分析、批量分析、专业报告导出等
  由 surgo 以自有实现另立 milestone，不抄其实现）
