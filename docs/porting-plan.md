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
> 基本面/财务（M3）、中文新闻（M5）后续 milestone 已补齐；数据层已端到端验证
> （600519/000001.SZ/300750 均可取数、point-in-time 过滤正确、指标计算正确、AAPL 无回归）；
> 完整 `surgo --ticker 600519 --date <D>` 报告需配置 LLM API key 后运行。

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

### M4 — A 股特色分析师 ✅ 已完成
- [x] 大盘分析师（index analyst）— 自包含（无 tool 调用），预取 A 股五大指数
  近期表现 + THS 行业板块快照，注入 prompt 由 LLM 分析
  - 新增 `vendors/ashare/overview.py`：`get_market_overview(symbol, trade_date)`
    预取上证/深证/创业板/沪深300/中证500 指数收盘价及 5D/20D 涨跌幅，
    以及 THS 行业板块快照（涨跌幅排名、资金净流入）
  - 新增 `agents/analysts/index_analyst.py`：预取数据注入 prompt，LLM 输出
    大盘环境报告（趋势判断、市场宽度、风险等级），非 A 股符号返回
    not-applicable sentinel
- [x] 板块分析师（sector analyst）— 自包含（无 tool 调用），预取板块分类与
  板块指数数据
  - 新增 `vendors/ashare/sectors.py`：`get_sector_info(symbol, trade_date)`
    预取股票 THS 行业板块归属（通过 cninfo 证监会行业分类 → 关键词匹配 THS
    90 个行业板块；匹配失败时尝试主营业务描述二次匹配）、板块表现快照、
    板块指数近 10 期 OHLCV
  - 新增 `agents/analysts/sector_analyst.py`：预取数据注入 prompt，LLM 输出
    板块轮动与同业对比报告，非 A 股符号返回 not-applicable sentinel
- [x] 中文社媒/舆情分析师（替代 StockTwits/Reddit 路径）
  - 实测：东方财富股吧/雪球/微博等中文社交平台无 clean、tokenless 的公开
    API 可用，不可移植。现有 sentiment analyst 对 A 股符号已可降级运作：
    `get_news` 走 M5 中文新闻路径（✅），StockTwits/Reddit 对 A 股代码自然
    返回 unavailable 占位（✅），analyst 输出基于新闻的情绪判断但无社交数据。
    诚实降级优于伪造数据。
- 参考 CN `tradingagents/agents/analysts/`，重写为挂到 surgo 引擎的干净实现：
  - CN 的 index/sector analyst 走 `core.tools.*`（专有层，不可移植），采用
    自包含模式（预取数据+LLM 解读，无 tool 调用）。本实现沿用自包含模式但
    数据层用 `vendors/ashare/` 的 tokenless 源（THS 行业板块指数、cninfo 分类），
    零 `app/`/`core/` 依赖
  - 新增 analyst 通过 `AnalystType` 枚举、`ANALYST_NODE_SPECS`、
    `analyst_factories`、`AgentState` 报告键、researchers prompt 注入、
    CLI 选择菜单完整接入；非 A 股运行时两大 analyst 返回 not-applicable
    sentinel，不影响美股/加密货币运行

### M5 — 中文财经新闻 ✅ 已完成
- [x] 从 CN `tradingagents/dataflows/news/` 提取中文新闻源（借鉴其源选型思路，重写为干净实现）
  - CN 的 `chinese_finance.py` 实测是**模拟数据骨架**（`_search_finance_news` 返回硬编码示例、
    股吧/媒体两路直接返回零置信度占位），无真实取数逻辑可移植；`realtime_news.py` 走
    Finnhub/AlphaVantage/NewsAPI 美股源 + 中文源聚合，但 `stock_info_global_cls`（财联社）
    与 `stock_news_main_cx`（财新）在本机**挂死不返回**（与 eastmoney kline 同款失败模式）。
  - 因此源选型实测重定：**个股新闻** `ak.stock_news_em`（eastmoney 搜索接口，本机可达，
    每股最近 ~100 条，带分钟级发布时间）；**宏观快讯** `ak.stock_info_global_ths`（同花顺 7x24）
    降级 `ak.stock_info_global_sina`（新浪 7x24），均带时间戳、无需 token
- [x] 接入 news analyst 工具链
  - 新增 `vendors/ashare/news.py`：`get_news`（个股，按发布时间过滤窗口）与
    `get_global_news`（中文宏观快讯，按 lookback 窗口过滤、去重、截断到 limit）
  - **point-in-time 按发布时间戳**：文章只在 `发布时间 <= 窗口结束日` 时可见（实测：窗口止于
    09-27 时 09-28 的段永平报道不可见）；无法解析时间戳的行仅在非历史运行保留（对齐
    `date_window.in_window` 的 undated 规则 #1126）
  - 滚动窗口 feed 语义：窗口早于 feed 覆盖范围时返回 `coverage_gap` sentinel（「不是没有新闻，
    是 feed 够不到」），窗口在覆盖内但无文章时才返回 NO_DATA（真实缺席）
  - 路由：`get_news` 走 `_ASHARE_METHODS` 符号短路（args[0] 即 ticker）；`get_global_news`
    的首参是日期，工具层注入 `company_of_interest` 为 `symbol` kwarg 供路由门识别——
    langgraph 的 `_inject_tool_args` 会剥离 LLM 自带的值再注入 state 值，模型无法伪造
    symbol 绕过 A-share 路由（已读源码确认）
  - 实测：600519/300750 个股新闻可取（真实文章）；中文宏观快讯可取（商务部 G20 答记者问等）；
    AAPL get_news/get_global_news 仍走 yfinance 无回归；ruff 通过；无 app/core 依赖

## 验收标准（每个 milestone）

- 引擎可运行：`surgo --ticker 600519 --date <D>` 产出完整研究报告
- point-in-time：分析日期 D 的报告只引用 D 当日及之前可得的数据（无未来函数）
- 回测网格在 A 股标的上可跑通并聚合评分
- 全部新代码 Apache-2.0，NOTICE 保持双血统声明

## 明确不做

- 不引入 TradingAgents-CN 的 `app/` / `frontend/` / `core/`（专有许可）
- 不实现其 Pro 功能的代码（Agent 工坊、定时分析、批量分析、专业报告导出等
  由 surgo 以自有实现另立 milestone，不抄其实现）
