"""Trading-calendar lookup by market.

The engine's point-in-time contract is date-based, but several paths reason
about *trading* days: the backtest grid should not schedule a cell on a date
the market never opens, and a run dated on a holiday should be understood to
price the most recent session. This module is the single place that knows which
days a market trades.

Coverage:
    A-share      exact, from sina's historical trading calendar (cached to disk)
    other markets  weekday approximation (Mon–Fri) — the US path has no bundled
                   holiday calendar, and changing its long-standing behavior is
                   out of scope here; an approximation that matches weekends is
                   strictly better than the previous every-day grid.

The A-share calendar is fetched once and cached under ``data_cache_dir``; a
missing or unreachable calendar degrades to the weekday approximation rather
than aborting the run (a calendar is an optimization for the grid, never a
hard dependency of a data path).
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.vendors.ashare.symbols import is_ashare

logger = logging.getLogger(__name__)

# A-share calendar cache file and how long it may be reused before refetching.
_CALENDAR_CACHE = "ashare-trading-calendar.csv"
_CALENDAR_TTL_DAYS = 7

_calendar_memo: frozenset[date] | None = None


def _fetch_ashare_calendar() -> frozenset[date] | None:
    """The full A-share trading calendar from sina, as a set of dates."""
    try:
        import akshare as ak
        import pandas as pd

        df = ak.tool_trade_date_hist_sina()
        days = frozenset(pd.to_datetime(df["trade_date"]).dt.date)
        return days or None
    except Exception as e:
        logger.warning("A-share trading calendar fetch failed: %s", e)
        return None


def _load_ashare_calendar() -> frozenset[date] | None:
    """The A-share trading calendar, from cache or freshly fetched."""
    global _calendar_memo
    if _calendar_memo is not None:
        return _calendar_memo

    cache_file = os.path.join(get_config()["data_cache_dir"], _CALENDAR_CACHE)
    now = date.today()

    if os.path.exists(cache_file):
        try:
            import pandas as pd

            mtime = date.fromtimestamp(os.path.getmtime(cache_file))
            if (now - mtime).days <= _CALENDAR_TTL_DAYS:
                df = pd.read_csv(cache_file)
                _calendar_memo = frozenset(pd.to_datetime(df["trade_date"]).dt.date)
                return _calendar_memo
        except Exception as e:
            logger.warning("A-share calendar cache unreadable, refetching: %s", e)

    days = _fetch_ashare_calendar()
    if days is not None:
        try:
            import pandas as pd

            os.makedirs(get_config()["data_cache_dir"], exist_ok=True)
            pd.DataFrame({"trade_date": sorted(days)}).to_csv(cache_file, index=False)
        except Exception as e:
            logger.warning("A-share calendar cache write failed: %s", e)
        _calendar_memo = days
    return _calendar_memo


def _weekday_set() -> frozenset[date]:
    """Weekday approximation for markets without a bundled holiday calendar."""
    start, end = date(1990, 1, 1), date.today() + timedelta(days=370)
    return frozenset(
        d for d in (start + timedelta(days=i) for i in range((end - start).days))
        if d.weekday() < 5
    )


def trading_days(ticker: str) -> frozenset[date]:
    """The set of days ``ticker``'s market trades.

    A-share symbols get the exact sina calendar (falling back to weekdays when
    it cannot be fetched); every other market gets the weekday approximation.
    """
    if is_ashare(ticker):
        return _load_ashare_calendar() or _weekday_set()
    return _weekday_set()


def is_trading_day(ticker: str, day: str) -> bool:
    """Whether ``day`` (YYYY-MM-DD) is a trading day for ``ticker``'s market."""
    try:
        d = datetime.strptime(str(day), "%Y-%m-%d").date()
    except ValueError:
        return False
    return d in trading_days(ticker)


def nearest_trading_day(ticker: str, day: str, direction: str = "backward") -> str:
    """The trading day on or nearest ``day`` for ``ticker``'s market.

    ``direction="backward"`` returns the most recent trading day on or before
    ``day`` (used to re-seat a grid cell onto a real session); ``"forward"``
    returns the next trading day on or after it. A day that already trades is
    returned unchanged. Bounded to within two weeks, after which ``day`` itself
    is returned (a market closed that long is a data problem, not a calendar one).
    """
    d = datetime.strptime(str(day), "%Y-%m-%d").date()
    days = trading_days(ticker)
    if d in days:
        return d.strftime("%Y-%m-%d")
    step = -1 if direction == "backward" else 1
    cursor = d
    for _ in range(14):
        cursor += timedelta(days=step)
        if cursor in days:
            return cursor.strftime("%Y-%m-%d")
    return d.strftime("%Y-%m-%d")


def filter_trading_days(ticker: str, dates: list[str]) -> list[str]:
    """Re-seat each date onto its nearest prior trading day, preserving order.

    Used by the backtest grid so a sweep over A-share tickers schedules cells on
    real sessions instead of every calendar day. Duplicates introduced by
    re-seating (a holiday and its neighbours all mapping to the same Friday) are
    collapsed, since one cell per trading day is the unit of work.
    """
    seen, out = set(), []
    for d in dates:
        seated = nearest_trading_day(ticker, d, "backward")
        if seated not in seen:
            seen.add(seated)
            out.append(seated)
    return out
