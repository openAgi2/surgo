"""Daily OHLCV loading for A-shares, mirroring the Yahoo loader's contract.

The engine's indicator code (``stockstats``) and the verified-snapshot tool are
written against a single frame shape — capitalized ``Date/Open/High/Low/Close/
Volume``, ascending, filtered so no row postdates the analysis date. This module
produces exactly that shape from the A-share upstream chain, so those consumers
work unchanged for mainland symbols.

Adjustment: bars are fetched 前复权 (``qfq``), matching the US path's
``auto_adjust=True``. Like that path, the series is downloaded up to today and
then filtered to ``as_of_date`` — the no-look-ahead guarantee is the row filter,
not the adjustment anchor, which is the same contract the upstream engine keeps.
"""

from __future__ import annotations

import logging
import os

import pandas as pd

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.files import replace_file

from .common import fetch_daily
from .symbols import normalize_ashare

logger = logging.getLogger(__name__)

# A latest row this many calendar days before the requested date is treated as
# stale. Spans the long CN holiday clusters (Spring Festival, National Day).
MAX_OHLCV_STALE_DAYS = 15

# How long a same-day cache may serve an as-of-today request before refetching.
OHLCV_CACHE_TTL_SECONDS = 900

_PRICE_COLS = ("Open", "High", "Low", "Close", "Volume")


def _fill_price_gaps(data: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with no close, then forward/back-fill remaining price gaps."""
    price_cols = [c for c in _PRICE_COLS if c in data.columns]
    data = data.dropna(subset=["Close"]).copy()
    data[price_cols] = data[price_cols].ffill().bfill()
    return data


def _assert_not_stale(
    data: pd.DataFrame,
    as_of_date: str,
    symbol: str,
    canonical: str,
    *,
    max_stale_days: int = MAX_OHLCV_STALE_DAYS,
) -> None:
    """Reject a frame whose latest row is far older than ``as_of_date``.

    Guards the dangerous case of a present-but-stale frame (a suspended or
    delisted symbol, or a bad upstream response) that would otherwise feed
    year-old prices into indicators.
    """
    if data is None or data.empty:
        return
    requested = pd.to_datetime(as_of_date, errors="coerce")
    if pd.isna(requested):
        return
    requested = requested.normalize()
    latest = pd.to_datetime(data["Date"], errors="coerce").dropna().max()
    if pd.isna(latest):
        return
    stale_days = (requested - latest.normalize()).days
    if stale_days > max_stale_days:
        raise NoMarketDataError(
            symbol,
            canonical,
            f"latest row is {latest.date()}, {stale_days} days before the "
            f"requested {requested.date()} (stale) — refusing to use it",
        )


def _cache_is_fresh(data_file, as_of_dt, now) -> bool:
    """Whether a cached download can serve this request (same day, within TTL)."""
    written = pd.Timestamp.fromtimestamp(os.path.getmtime(data_file))
    if written.date() != now.date():
        return False
    return as_of_dt.date() < now.date() or (now - written).total_seconds() <= OHLCV_CACHE_TTL_SECONDS


def load_ohlcv(symbol: str, as_of_date: str, fill_gaps: bool = True) -> pd.DataFrame:
    """Fetch A-share daily OHLCV, cached per symbol, filtered to ``as_of_date``.

    Downloads five years up to today on a cache miss and reuses the cache
    otherwise. Rows after ``as_of_date`` are dropped so backtests never see
    future prices. ``fill_gaps`` carries prices over gaps so indicators compute
    on a continuous series; pass ``False`` to keep the values as reported.
    """
    canonical = normalize_ashare(symbol)

    config = get_config()
    as_of_dt = pd.to_datetime(as_of_date).normalize()
    now = pd.Timestamp.today()
    start_str = (now - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    end_str = now.strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(config["data_cache_dir"], f"{canonical}-AShare-data.csv")

    data = None
    if os.path.exists(data_file):
        cached = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
        if not cached.empty and "Close" in cached.columns and _cache_is_fresh(data_file, as_of_dt, now):
            data = cached

    if data is None:
        data = fetch_daily(symbol, start_str, end_str, adjust="qfq")
        if data.empty or "Close" not in data.columns:
            raise NoMarketDataError(symbol, canonical, "no price rows")
        replace_file(data_file, lambda temp: data.to_csv(temp, index=False, encoding="utf-8"))

    data = data.copy()
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])
    data = data[data["Date"] <= as_of_dt]

    if not data.empty and pd.isna(data["Close"].iloc[-1]):
        settled = data["Close"].notna().to_numpy().nonzero()[0]
        if settled.size == 0:
            raise NoMarketDataError(symbol, canonical, "no bar in range has a closing price")
        logger.warning(
            "%s: %d trailing bar(s) through %s have no closing price; using %s as the latest close.",
            canonical, len(data) - settled[-1] - 1,
            data["Date"].iloc[-1].date(), data["Date"].iloc[settled[-1]].date(),
        )

    data = _fill_price_gaps(data) if fill_gaps else data.dropna(subset=["Close"]).copy()
    _assert_not_stale(data, as_of_date, symbol, canonical)
    return data
