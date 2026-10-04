"""What every A-share request shares: the upstream chain and error mapping.

The four upstreams differ in reachability, auth and protocol, so a single
ordered fallback chain is centralized here rather than re-derived at each call
site. The order reflects what is reachable without credentials:

    1. akshare -> sina     (keyless, full qfq/hfq/raw adjust support)
    2. akshare -> tencent  (keyless, qfq/hfq/raw)
    3. baostock            (keyless, own socket protocol)
    4. tushare             (needs TUSHARE_TOKEN; skipped when unset)

eastmoney (akshare's default ``stock_zh_a_hist``) is deliberately excluded: it
is unreachable from common CN-adjacent networks and its failure mode is a hung
connection, not a clean error, so it would stall the chain.
"""

from __future__ import annotations

import logging
import os

import pandas as pd

from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorUnavailableError,
)

from .symbols import to_baostock, to_sina, to_tushare

logger = logging.getLogger(__name__)

# akshare's sina/tencent endpoints return Chinese column headers; normalize to
# the engine's OHLCV vocabulary. Only the columns the engine consumes are
# mapped; the rest (amount, turnover, ...) are passed through untouched.
_SINA_COLUMNS = {
    "date": "Date",
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume": "Volume",
}

# eastmoney's kline endpoint returns Chinese headers with a different spelling
# than sina's; map the OHLCV columns the same way.
_EM_COLUMNS = {
    "日期": "Date",
    "开盘": "Open",
    "最高": "High",
    "最低": "Low",
    "收盘": "Close",
    "成交量": "Volume",
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename an upstream frame's date/OHLCV columns to the engine's contract."""
    out = df.copy()
    for c in out.columns:
        key = str(c).lower()
        if key in _SINA_COLUMNS:
            out = out.rename(columns={c: _SINA_COLUMNS[key]})
        elif c in _EM_COLUMNS:
            out = out.rename(columns={c: _EM_COLUMNS[c]})
    return out


class AShareNotConfiguredError(VendorNotConfiguredError):
    """A tushare call was attempted without TUSHARE_TOKEN set."""


def get_tushare_token() -> str:
    """The tushare API token from the environment, or raise if absent."""
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise AShareNotConfiguredError(
            "TUSHARE_TOKEN environment variable is not set."
        )
    return token


def _finalize(df: pd.DataFrame, symbol: str, canonical: str) -> pd.DataFrame:
    """Normalize an upstream frame to the engine's OHLCV contract.

    Renames to capitalized columns, parses ``Date`` to midnight-normalized
    timestamps, coerces prices to numeric, sorts ascending, and drops rows with
    no close. Raises ``NoMarketDataError`` when nothing usable remains so the
    router emits one clear unavailable signal instead of an empty frame.
    """
    if df is None or df.empty:
        raise NoMarketDataError(symbol, canonical, "no price rows")

    out = _normalize_columns(df)
    if "Date" not in out.columns:
        raise NoMarketDataError(symbol, canonical, f"no date column in {list(df.columns)}")

    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out = out.dropna(subset=["Date"]).copy()
    out["Date"] = out["Date"].dt.normalize()

    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.sort_values("Date").reset_index(drop=True)
    out = out.dropna(subset=["Close"])
    if out.empty:
        raise NoMarketDataError(symbol, canonical, "no rows with a closing price")
    return out


def _fetch_eastmoney(symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
    """Daily bars from eastmoney's kline endpoint, requested directly.

    eastmoney's kline is the richest A-share source (turnover, amplitude, etc.)
    and needs no token. Its host is SNI-blocked on some networks and reachable
    on others, and the working path (direct vs system proxy) varies — so the
    request is hand-built (rather than via akshare, which always uses the
    ambient proxy) and tried direct first, then through the system proxy. It is
    placed after sina in the chain so the stable path never pays its failure cost.
    """
    import requests

    fqt = {"qfq": "1", "hfq": "2", "": "0"}.get(adjust, "1")
    secid = f"{'1' if to_sina(symbol).startswith('sh') else '0' if to_sina(symbol).startswith('sz') else '0'}.{to_sina(symbol)[2:]}"
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": "101", "fqt": fqt, "secid": secid,
        "beg": start_date.replace("-", ""), "end": end_date.replace("-", ""),
    }
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    rows = None
    for session in (requests.Session(), None):
        if session is not None:
            session.trust_env = False
        try:
            client = session or requests
            data = client.get(url, params=params, timeout=15).json()
            klines = (data.get("data") or {}).get("klines") or []
            rows = [k.split(",") for k in klines]
            if rows:
                break
        except Exception:
            continue
    if not rows:
        raise VendorUnavailableError(f"eastmoney returned no kline rows for {symbol}")
    df = pd.DataFrame(rows, columns=["Date", "Open", "Close", "High", "Low", "Volume",
                                     "amount", "amplitude", "change_percent", "change", "turnover"])
    return _finalize(df, symbol, to_sina(symbol))


def _fetch_sina(symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
    """Daily bars from sina via akshare's ``stock_zh_a_daily``."""
    import akshare as ak

    df = ak.stock_zh_a_daily(
        symbol=to_sina(symbol),
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        adjust=adjust,
    )
    return _finalize(df, symbol, to_sina(symbol))


def _fetch_tencent(symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
    """Daily bars from tencent via akshare's ``stock_zh_a_hist_tx``."""
    import akshare as ak

    df = ak.stock_zh_a_hist_tx(
        symbol=to_sina(symbol),
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        adjust=adjust,
    )
    return _finalize(df, symbol, to_sina(symbol))


def _fetch_baostock(symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
    """Daily bars from baostock's own socket protocol.

    baostock uses a stateful login/logout session, not HTTP, so it is unaffected
    by HTTP proxy settings. ``adjustflag`` is ``2`` (qfq) / ``1`` (hfq) /
    ``3`` (raw).
    """
    import baostock as bs

    adjustflag = {"qfq": "2", "hfq": "1", "": "3"}.get(adjust, "2")
    lg = bs.login()
    if lg.error_code != "0":
        raise VendorUnavailableError(f"baostock login failed: {lg.error_msg}")
    try:
        rs = bs.query_history_k_data_plus(
            to_baostock(symbol),
            "date,open,high,low,close,volume",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag=adjustflag,
        )
        if rs.error_code != "0":
            raise VendorUnavailableError(f"baostock query failed: {rs.error_msg}")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        df = pd.DataFrame(rows, columns=rs.fields)
    finally:
        bs.logout()
    return _finalize(df, symbol, to_baostock(symbol))


def _fetch_tushare(symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
    """Daily bars from tushare pro. Requires TUSHARE_TOKEN."""
    import tushare as ts

    token = get_tushare_token()
    ts.set_token(token)
    pro = ts.pro_api()
    ts_code = to_tushare(symbol)
    adj = {"qfq": "qfq", "hfq": "hfq", "": None}.get(adjust, "qfq")
    df = ts.pro_bar(
        ts_code=ts_code,
        api=pro,
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        freq="D",
        adj=adj,
    )
    if df is None or df.empty:
        raise NoMarketDataError(symbol, ts_code, "no price rows")
    # tushare returns English snake_case columns; map to the engine's contract.
    df = df.rename(columns={"trade_date": "Date", "open": "Open", "high": "High",
                            "low": "Low", "close": "Close", "vol": "Volume"})
    return _finalize(df, symbol, ts_code)


# Ordered (name, fetcher) chain. sina first: it is stable and direct-reachable,
# so the common path never pays for a probe of a source that may be blocked.
# eastmoney follows (richest fields, but SNI-blocked on some networks — tried
# direct then via the system proxy). tushare is attempted last because it
# requires a token and raises AShareNotConfiguredError when unset, which the
# chain treats as "skip".
_CHAIN = (
    ("sina", _fetch_sina),
    ("eastmoney", _fetch_eastmoney),
    ("tencent", _fetch_tencent),
    ("baostock", _fetch_baostock),
    ("tushare", _fetch_tushare),
)


def fetch_daily(symbol: str, start_date: str, end_date: str, adjust: str = "qfq") -> pd.DataFrame:
    """Fetch A-share daily OHLCV, walking the fallback chain.

    Returns a normalized frame (Date/Open/High/Low/Close/Volume, ascending,
    close-bearing rows only) from the first upstream that answers. Raises
    ``NoMarketDataError`` when every reachable upstream reported no data, and
    ``VendorUnavailableError`` when every upstream failed in transit — the
    router turns each into the matching sentinel.
    """
    last_no_data: NoMarketDataError | None = None
    last_unavailable: VendorUnavailableError | None = None
    for name, fetcher in _CHAIN:
        try:
            return fetcher(symbol, start_date, end_date, adjust)
        except AShareNotConfiguredError as e:
            logger.debug("ashare upstream %s not configured; skipping: %s", name, e)
            continue
        except NoMarketDataError as e:
            last_no_data = e
            continue
        except VendorUnavailableError as e:
            last_unavailable = e
            logger.warning("ashare upstream %s unavailable: %s", name, e)
            continue
        except Exception as e:
            # An unexpected upstream error (network reset, schema change) is a
            # transport failure, not a verdict about the symbol.
            last_unavailable = VendorUnavailableError(f"ashare upstream {name} failed: {e}")
            logger.warning("ashare upstream %s failed: %s", name, e)
            continue

    if last_no_data is not None and last_unavailable is None:
        raise last_no_data
    if last_unavailable is not None:
        raise last_unavailable
    raise NoMarketDataError(symbol, symbol, "no A-share upstream returned data")
