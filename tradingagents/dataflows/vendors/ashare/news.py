"""A-share news: per-ticker headlines and a Chinese-language macro/flash feed.

The US news vendors (yfinance, Alpha Vantage) cover US listings; for a mainland
symbol they return empty or the wrong instrument. This vendor serves two Chinese
sources, both keyless and reachable without a token:

    per-ticker news   akshare ``stock_news_em`` (eastmoney's per-stock news feed;
                      carries a publish timestamp per article)
    macro/flash news  akshare ``stock_info_global_ths`` (同花顺 7x24 live wire,
                      timestamped), falling back to ``stock_info_global_sina``
                      (sina 7x24 wire, timestamped)

Point-in-time is by publish timestamp: every article is filtered to
``published <= as_of_date`` (and within the requested window), so a backtest
dated D is never shown a story that ran after D. Articles whose timestamp cannot
be parsed are kept only for a non-historical (present-day) run, matching the
engine's ``date_window.in_window`` rule for undated items.

The ``stock_info_global_cls`` (财联社) and ``stock_news_main_cx`` (财新) akshare
endpoints are deliberately excluded: from common CN-adjacent networks they hang
the connection instead of answering (the same failure mode as eastmoney's
kline), so they would stall every news call.

This borrows *which* sources serve A-share news from TradingAgents-CN's
Apache-2.0 engine, re-implemented cleanly against the surgo vendor contract
(no app/core, no copied code).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Annotated

import pandas as pd

from tradingagents.dataflows.date_window import coverage_gap, is_historical
from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError

from .symbols import ashare_code, normalize_ashare

logger = logging.getLogger(__name__)


def _fetch_ticker_news(symbol: str) -> pd.DataFrame:
    """eastmoney's per-stock news frame for an A-share symbol."""
    import akshare as ak

    code = ashare_code(symbol)
    try:
        df = ak.stock_news_em(symbol=code)
    except Exception as e:
        raise VendorUnavailableError(f"eastmoney per-stock news fetch failed: {e}") from e
    if df is None or df.empty:
        raise NoMarketDataError(symbol, code, "no per-stock news rows")
    return df


def _fetch_global_news() -> pd.DataFrame:
    """The first reachable macro/flash wire, in reachability order.

    同花顺 (ths) is tried first because it carries a stable per-item timestamp;
    sina is the fallback. Each returns its latest items, so the frame is merged
    and de-duplicated downstream before the point-in-time filter is applied.
    """
    import akshare as ak

    errors = []
    for name, fn in (("ths", ak.stock_info_global_ths), ("sina", ak.stock_info_global_sina)):
        try:
            df = fn()
        except Exception as e:
            errors.append(f"{name}: {e}")
            logger.warning("A-share global news source %r failed: %s", name, e)
            continue
        if df is not None and not df.empty:
            return df
        errors.append(f"{name}: no rows")
    raise VendorUnavailableError("; ".join(errors) or "no A-share global news source reachable")


def _in_window(ts: pd.Timestamp | pd.NaT, start: datetime, end: datetime) -> bool:
    """Whether an item belongs in the half-open window ``[start, end + 1 day)``.

    Mirrors ``date_window.in_window`` for this vendor's naive local timestamps:
    an item at any time on ``end`` counts. Unparseable timestamps are handled by
    the caller (kept only for a present-day run), never passed here.
    """
    return start <= ts < end + timedelta(days=1)


def get_news(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """eastmoney per-stock news for an A-share symbol, within a date window."""
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    canonical = normalize_ashare(symbol)

    df = _fetch_ticker_news(symbol)
    pub = pd.to_datetime(df["发布时间"], errors="coerce")

    # Point-in-time: an article counts only once published (<= end of window).
    # Undated rows are kept only for a non-historical run (#1126).
    dated = pub.notna()
    in_win = pd.Series(False, index=df.index)
    in_win[dated] = pub[dated].map(lambda ts: _in_window(ts, start_dt, end_dt))
    if not is_historical(end_date):
        in_win |= ~dated
    keep = df[in_win]

    label = canonical if canonical == symbol.upper() else f"{canonical} (from {symbol})"
    if keep.empty:
        # The feed is a rolling window of recent items, so "nothing in this
        # window" usually means the window is older than the feed reaches, not
        # that the symbol had no news. Report the coverage gap plainly rather
        # than a bare no-data that reads as an absence (#993-style).
        gap = coverage_gap(pub[dated], start_date, end_date, "eastmoney news", f"news for {label}")
        if gap:
            return gap
        raise NoMarketDataError(
            symbol, canonical, f"no news between {start_date} and {end_date}"
        )

    body = ""
    for _, row in keep.iterrows():
        title = str(row.get("新闻标题", "No title")).strip()
        source = str(row.get("文章来源", "Unknown")).strip()
        summary = str(row.get("新闻内容", "")).strip()
        link = str(row.get("新闻链接", "")).strip()
        body += f"### {title} (source: {source})\n"
        if summary:
            body += f"{summary}\n"
        if link:
            body += f"Link: {link}\n"
        body += "\n"

    header = f"## {label} News, from {start_date} to {end_date}:\n\n"
    return header + body


def get_global_news(
    as_of_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int | None, "Days to look back"] = None,
    limit: Annotated[int | None, "Max articles to return"] = None,
) -> str:
    """Chinese-language macro/flash news over a lookback window ending at as_of_date."""
    from tradingagents.dataflows.config import get_config

    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]

    end_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    df = _fetch_global_news()

    # Normalize the two wires to one vocabulary: ths has 标题/内容/发布时间/链接,
    # sina has 时间/内容 (no title, no link).
    if "发布时间" in df.columns:
        ts_col, title_col, link_col = "发布时间", "标题", "链接"
    else:
        ts_col, title_col, link_col = "时间", None, None

    pub = pd.to_datetime(df[ts_col], errors="coerce")
    dated = pub.notna()
    in_win = pd.Series(False, index=df.index)
    in_win[dated] = pub[dated].map(lambda ts: _in_window(ts, start_dt, end_dt))
    if not is_historical(as_of_date):
        in_win |= ~dated
    keep = df[in_win]

    if keep.empty:
        gap = coverage_gap(
            pub[dated], start_date, as_of_date, "A-share macro wire", "China macro news"
        )
        if gap:
            return gap
        raise NoMarketDataError(
            "GLOBAL", "A-share macro wire", f"no global news between {start_date} and {as_of_date}"
        )

    # Newest first, de-duplicated on content, capped at the article limit.
    keep = keep.assign(_pub=pub[keep.index]).sort_values("_pub", ascending=False)
    seen = set()
    body = ""
    count = 0
    for _, row in keep.iterrows():
        content = str(row.get("内容", "")).strip()
        if not content or content in seen:
            continue
        seen.add(content)
        title = str(row.get(title_col, "")).strip() if title_col else ""
        link = str(row.get(link_col, "")).strip() if link_col else ""
        ts = row.get(ts_col, "")
        head = title if title else content[:60]
        body += f"### {head} (time: {ts})\n"
        if content and content != title:
            body += f"{content}\n"
        if link:
            body += f"Link: {link}\n"
        body += "\n"
        count += 1
        if count >= limit:
            break

    if not body:
        raise NoMarketDataError(
            "GLOBAL", "A-share macro wire", f"no global news between {start_date} and {as_of_date}"
        )

    header = f"## A-share / China Macro News, from {start_date} to {as_of_date}:\n\n"
    return header + body
