"""A-share fundamentals: statements, overview, and a present-day company profile.

Unlike the Yahoo path, whose statement endpoints carry no disclosure date (so a
past run must withhold them wholesale), akshare's eastmoney ``*_by_report_em``
endpoints return each filing's ``NOTICE_DATE`` — the day it was actually
announced. That makes a true as-filed, point-in-time read possible for mainland
filings: a run dated D is served only the rows whose ``NOTICE_DATE <= D``, so a
report published after D is never shown to it.

Data sources (all reachable without a token):
    three statements   akshare ``stock_{balance,profit,cash_flow}_sheet_by_report_em``
    company profile    akshare ``stock_profile_cninfo`` (cninfo; present-day snapshot)
    market cap / PE    close x shares outstanding from the OHLCV chain, and a
                       TTM net profit summed from already-disclosed filings

This borrows *which* endpoints serve A-share filings and their disclosure-date
semantics from TradingAgents-CN's Apache-2.0 engine, re-implemented cleanly
against the surgo vendor contract (no app/core, no copied code).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

import pandas as pd

from tradingagents.dataflows.date_window import is_historical
from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError

from .ohlcv import load_ohlcv
from .symbols import normalize_ashare

logger = logging.getLogger(__name__)


def _em_symbol(symbol: str) -> str:
    """eastmoney's exchange-prefixed code: ``600519.SH`` -> ``SH600519``."""
    c = normalize_ashare(symbol)          # e.g. 600519.SH
    code, exch = c.split(".")             # 600519, SH
    return f"{exch}{code}"


def _fetch_statement(symbol: str, kind: str) -> pd.DataFrame:
    """One statement, all periods, newest first, as filed by eastmoney."""
    import akshare as ak

    em = _em_symbol(symbol)
    fn = {
        "balance": ak.stock_balance_sheet_by_report_em,
        "income": ak.stock_profit_sheet_by_report_em,
        "cashflow": ak.stock_cash_flow_sheet_by_report_em,
    }[kind]
    try:
        df = fn(symbol=em)
    except Exception as e:
        raise VendorUnavailableError(f"eastmoney {kind} statement fetch failed: {e}") from e
    if df is None or df.empty:
        raise NoMarketDataError(symbol, em, f"no {kind} statement rows")
    return df


def _as_filed(df: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    """Rows whose disclosure date is on or before ``as_of_date``.

    The point-in-time filter: a filing counts only once it is public
    (``NOTICE_DATE <= as_of_date``), regardless of the period it covers. Rows
    without a disclosure date are kept only for a non-historical (present-day)
    run, since a backtest cannot prove they were public (#1126).
    """
    if "NOTICE_DATE" not in df.columns:
        return df if not is_historical(as_of_date) else df.iloc[0:0]
    notice = pd.to_datetime(df["NOTICE_DATE"], errors="coerce")
    cutoff = pd.to_datetime(as_of_date)
    return df[notice <= cutoff]


def _select_periods(df: pd.DataFrame, freq: str, limit: int = 8) -> pd.DataFrame:
    """Latest ``limit`` periods of the requested frequency (annual = 年报)."""
    if "REPORT_TYPE" in df.columns:
        want = "年报" if freq.lower() == "annual" else None
        if want:
            df = df[df["REPORT_TYPE"] == want]
    if "REPORT_DATE" in df.columns:
        df = df.sort_values("REPORT_DATE", ascending=False)
    return df.head(limit)


# Key financial columns to surface, per statement. eastmoney returns 200+ columns;
# the analysts need the standard lines, not the full filing. Chosen to mirror the
# fields the Yahoo path exposes (revenue, net income, assets, liabilities, cash flows).
_KEY_COLUMNS = {
    "balance": ["TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY", "TOTAL_PARENT_EQUITY",
                "MONETARYFUNDS", "ACCOUNTS_RECE", "INVENTORY", "FIXED_ASSET"],
    "income": ["TOTAL_OPERATE_INCOME", "OPERATE_INCOME", "OPERATE_COST", "OPERATE_PROFIT",
               "TOTAL_PROFIT", "NETPROFIT", "PARENT_NETPROFIT", "DEDUCT_PARENT_NETPROFIT",
               "BASIC_EPS", "RESEARCH_EXPENSE"],
    "cashflow": ["NETCASH_OPERATE", "NETCASH_INVEST", "NETCASH_FINANCE", "CCE_ADD",
                 "BEGIN_CCE", "END_CCE"],
}


def _statement(symbol: str, freq: str, as_of_date: str, kind: str, title: str) -> str:
    """One statement as CSV, as filed on or before ``as_of_date``."""
    canonical = normalize_ashare(symbol)
    df = _fetch_statement(symbol, kind)
    df = _as_filed(df, as_of_date)
    df = _select_periods(df, freq)
    if df.empty:
        raise NoMarketDataError(
            symbol, canonical,
            f"no {title.lower()} filing disclosed on or before {as_of_date}",
        )
    # Keep the disclosure columns visible so the reader can see each row's vintage.
    keep = [c for c in ("REPORT_DATE_NAME", "REPORT_DATE", "REPORT_TYPE", "NOTICE_DATE") if c in df.columns]
    value_cols = [c for c in _KEY_COLUMNS.get(kind, []) if c in df.columns]
    out = df[keep + value_cols].copy()
    for c in ("REPORT_DATE", "NOTICE_DATE"):
        if c in out.columns:
            out[c] = pd.to_datetime(out[c], errors="coerce").dt.strftime("%Y-%m-%d")
    header = (
        f"# {title} data for {canonical} ({freq})\n"
        f"# Point-in-time as of: {as_of_date} — only filings with NOTICE_DATE <= {as_of_date}\n"
    )
    return header + out.to_csv(index=False)


def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    as_of_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Balance sheet, as filed on or before ``as_of_date``."""
    return _statement(ticker, freq, as_of_date or datetime.today().strftime("%Y-%m-%d"),
                      "balance", "Balance Sheet")


def get_income_statement(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    as_of_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Income statement, as filed on or before ``as_of_date``."""
    return _statement(ticker, freq, as_of_date or datetime.today().strftime("%Y-%m-%d"),
                      "income", "Income Statement")


def get_cashflow(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    as_of_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Cash flow statement, as filed on or before ``as_of_date``."""
    return _statement(ticker, freq, as_of_date or datetime.today().strftime("%Y-%m-%d"),
                      "cashflow", "Cash Flow")


def _ttm_net_profit(symbol: str, as_of_date: str) -> float | None:
    """Trailing-twelve-month attributable net profit from already-disclosed filings.

    Sums the four most recent quarterly ``PARENT_NETPROFIT`` periods disclosed by
    ``as_of_date``. Returns None when fewer than four quarterly filings are
    public (a TTM built on three quarters would be a fabrication).
    """
    df = _as_filed(_fetch_statement(symbol, "income"), as_of_date)
    if df.empty or "PARENT_NETPROFIT" not in df.columns:
        return None
    df = df.sort_values("REPORT_DATE", ascending=False).head(4)
    profits = pd.to_numeric(df["PARENT_NETPROFIT"], errors="coerce").dropna()
    return float(profits.sum()) if len(profits) >= 4 else None


def get_fundamentals(
    ticker: Annotated[str, "ticker symbol of the company"],
    as_of_date: Annotated[str, "analysis date in YYYY-MM-DD format"] = None,
) -> str:
    """Company fundamentals overview, as of ``as_of_date``.

    Profile fields (name, industry, main business) come from cninfo, which is a
    present-day snapshot with no historical vintage; a past run is told so via
    the shared ``withhold_live_profile`` guard. Valuation fields (market cap,
    PE) are computed from point-in-time-safe inputs (the close on the analysis
    date and filings disclosed by it).
    """
    as_of_date = as_of_date or datetime.today().strftime("%Y-%m-%d")
    canonical = normalize_ashare(ticker)

    fields: list[tuple[str, object]] = []

    # Company profile from cninfo is a present-day snapshot with no historical
    # vintage (name, industry, even the listing date reflect today). Withhold it
    # from a historical run, but still serve the point-in-time-safe valuation
    # fields below, which are computed from the close on the analysis date and
    # filings disclosed by it.
    if not is_historical(as_of_date):
        try:
            import akshare as ak

            prof = ak.stock_profile_cninfo(symbol=normalize_ashare(ticker).split(".")[0])
            if prof is not None and not prof.empty:
                row = prof.iloc[0]
                for label, col in (("Name", "公司名称"), ("A-share Abbreviation", "A股简称"),
                                   ("Industry", "所属行业"), ("Market", "所属市场"),
                                   ("Main Business", "主营业务"), ("List Date", "上市日期")):
                    v = row.get(col)
                    if v is not None and str(v).strip():
                        fields.append((label, v))
        except Exception as e:
            logger.warning("cninfo profile fetch failed for %s: %s", canonical, e)

    # Valuation from point-in-time-safe inputs.
    try:
        bars = load_ohlcv(ticker, as_of_date, fill_gaps=False)
        latest = bars.iloc[-1]
        close = float(latest["Close"])
        fields.append(("Latest Close", round(close, 2)))
        shares = latest.get("outstanding_share")
        if shares is not None and pd.notna(shares) and float(shares) > 0:
            mkt_cap = close * float(shares)
            fields.append(("Market Cap", f"{mkt_cap / 1e8:.2f} 亿元"))
            ttm = _ttm_net_profit(ticker, as_of_date)
            if ttm and ttm > 0:
                fields.append(("Net Income (TTM)", f"{ttm / 1e8:.2f} 亿元"))
                fields.append(("PE Ratio (TTM)", round(mkt_cap / ttm, 2)))
    except Exception as e:
        logger.warning("A-share valuation computation failed for %s: %s", canonical, e)

    if not fields:
        raise NoMarketDataError(ticker, canonical, "no fundamental fields")
    lines = [f"{label}: {v}" for label, v in fields]
    return f"# Company Fundamentals for {canonical}\n\n" + "\n".join(lines)


def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol of the company"],
    as_of_date: Annotated[str | None, "analysis date, yyyy-mm-dd"] = None,
) -> str:
    """Insider transactions — not served by this vendor.

    The reachable A-share endpoints do not expose insider filings with a
    disclosure date, so a point-in-time-safe read is impossible. Reported
    plainly rather than estimated.
    """
    canonical = normalize_ashare(ticker)
    return (
        f"# Insider Transactions for {canonical}\n"
        f"# Point-in-time as of: {as_of_date}\n\n"
        f"Insider transaction data is not available for this A-share symbol. The "
        f"reachable mainland endpoints do not expose insider filings with a "
        f"disclosure date, so a point-in-time-safe read cannot be made. Do not "
        f"estimate or fabricate insider activity."
    )
