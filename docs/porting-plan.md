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

### M1 — A 股行情 vendor ✅ 已完成（数据层验证通过）
- [x] 研究原版 vendor 抽象：`tradingagents/dataflows/vendors/`（`router.py` / `base`）
- [x] 从 CN `tradingagents/dataflows/` 提取 tushare/akshare/baostock 的行情获取逻辑
  （日线、实时快照、指数、板块），剥离其对 `app/`/`core/` 的依赖
- [x] 在 surgo 引擎内实现为新的 vendor 模块：`tradingagents/dataflows/vendors/ashare/`
  （clean-room 重写，实际文件：`symbols.py` 代码识别、`common.py` 降级链、
  `ohlcv.py` 日线加载、`market.py` 工具函数 + 指数 `get_closes`）
  - [x] 降级链 sina → tencent → baostock → tushare（eastmoney 不可达故排除；tushare 需 `TUSHARE_TOKEN`，可选）
  - [x] 复权 `qfq`（对齐原版 `auto_adjust=True` 语义）
- [x] 接入原版 vendor 注册表：`router.py` 对 A 股符号短路到 ashare（`get_stock_data`/`get_indicators`），
  `snapshot.py` 与 `memory/settlement.py` 按市场分发；benchmark 加 `.SH`→`000001.SH` 映射
- [x] 依赖：在 `pyproject.toml` 增加 `tushare` / `akshare` / `baostock`

> M1 范围说明（按 handoff 退路收紧）：只做行情 + 技术指标 + 回测结算数据路径。
> 基本面/财务（M3）、中文新闻（M5）、实时快照工具未实现，A 股符号调用这些方法时
> 走既有链或返回明确 sentinel，不伪造数据。数据层已端到端验证（600519/000001.SZ/300750
> 均可取数、point-in-time 过滤正确、指标计算正确、AAPL 无回归）；完整 `surgo --ticker
> 600519 --date <D>` 报告需配置 LLM API key 后运行。

> **eastmoney 为何被排除（不要踩第二次，2026-10-04 实测）**：akshare 默认的
> A 股日线源 eastmoney（`push2his.eastmoney.com` / `push2.eastmoney.com` 的
> `/api/qt/stock/kline/get`）在开发机上**不可达，且不是代理配置能稳定解决的**。
> 诊断结论：TCP 握手 ✅、TLS 握手 ✅（证书正常下发）、HTTP 响应 ❌（发出后 0 字节返回）
> —— 典型的 **SNI 级阻断**（在 TLS ClientHello 看到 `eastmoney.com` 相关 SNI 即断流）。
> 同一 CDN 的 `82.push2.eastmoney.com/api/qt/clist/get` 偶发返回 200，是 fake-IP 恰好走
> 了某个能通的境外中转节点，重试即失败、不可依赖。**DIRECT 规则救不了它**（SNI 拦截在
> 直连路径上同样生效）。因此降级链定为 sina → tencent → baostock → tushare，全部实测可达、
> 无需代理。若后续要把 eastmoney 加回首选，前提是其代理节点已调稳，否则会给链上引入
> 一个必败且拖慢整条链的源。
>
> **2026-10-04 更新**：eastmoney kline 可达性**随时间波动**（间歇性可达——同一台机器
> curl/requests 直连时通时断，与代理节点切换相关）。已将其加回降级链 **sina 之后**作为
> 机会性源（`common.py` 的 `_fetch_eastmoney`，手写直连请求 + 系统代理 fallback）：
> sina 稳定时用不到它；sina 失败且它可达时享受其更全字段（换手率/振幅）；不可达时
> 降级链继续走 tencent/baostock，不拖慢主路径。注意 eastmoney 的**财务**接口
> （`*_by_report_em`）走不同主机，稳定可达，M3 三表依赖它。

### M2 — A 股代码与交易日历 ✅ 已完成
- [x] A 股代码识别与归一化（`600519.SH` / `000001.SZ` / 6 位简码）— 在 M1 `vendors/ashare/symbols.py` 落地
- [x] A 股交易日历（用于 point-in-time 与回测网格，替换原版美股日历假设）
  - 新增 `tradingagents/calendar.py`：A 股用 sina 交易日历（`tool_trade_date_hist_sina`，8797 天，
    1990→2026，正确排除国庆/周末），缓存到 `data_cache_dir`（TTL 7 天）；其他市场回退「周一到周五」
    近似（美股无现成日历源，不改其行为）
  - 回测网格：`iter_grid(..., tickers=...)` 对**纯 A 股**网格按交易日重排 cell（`filter_trading_days`
    把非交易日 cell 换到最近一个交易日并去重）；美股/混合网格维持原 every-day 行为（只做加法）
  - 单日运行（`_validate_trade_date`）不改：A 股非交易日自然取最近一根 bar，stale guard 兜底，
    与美股周末行为一致
  - 实测：2025 国庆假期（10-01..10-08）全部正确判为非交易日，grid 从 15 天收敛到 5 个交易日

### M3 — A 股基本面与财务 ✅ 已完成
- [x] 财务三表 / 主要指标（替代 SEC EDGAR 路径）
  - 新增 `vendors/ashare/fundamentals.py`：三表走 akshare eastmoney 财务接口
    （`stock_{balance,profit,cash_flow}_sheet_by_report_em`，本机可达、无需 token），
    精简为标准财务列（营收/净利/总资产/总负债/经营现金流等）
  - 公司概况走 cninfo（`stock_profile_cninfo`，现状快照）；估值（市值/PE TTM）本地算：
    `close × outstanding_share`（M1 sina 行情）÷ 已披露归母净利 TTM
  - insider transactions：可达的 A 股端点无披露日字段，返回明确 sentinel（不伪造）
- [x] 保留原版的「as-filed / point-in-time」语义：按分析日期只取当时已披露的财报
  - eastmoney 三表自带 `NOTICE_DATE`（实际公告日）——比 Yahoo 路径更强：Yahoo 无披露日，
    历史日期只能整体 withhold；A 股路径可按公告日逐行过滤，真正做到 as-filed
  - 实测公告日矩阵：as_of 2025-04-15→见 2024年报（4-03 披露）、2025-05-01→见一季报
    （4-30 披露）、2025-10-30→见三季报（当天披露）；公告日当天可见、前一天不可见
  - 历史日期概况字段（cninfo 现状快照）按 `is_historical` withhold；估值字段
    （point-in-time 安全输入）照常给出
- 接入：`router.py` 的 `_ASHARE_METHODS` 增加 5 个财务方法，A 股符号自动短路

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
