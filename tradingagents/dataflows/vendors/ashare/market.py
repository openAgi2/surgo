"""The A-share market-data tool implementations.

Two router-facing entry points, mirroring the Yahoo vendor's output contract so
the analysts' prompts and report assembly work unchanged for mainland symbols:

    get_stock_data      formatted OHLCV CSV between two dates
    get_indicators      a technical indicator series, computed locally by
                        stockstats off the A-share OHLCV frame

Indicator math is the same ``stockstats`` engine the Yahoo path uses; only the
source of the OHLCV frame differs.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

import pandas as pd
from dateutil.relativedelta import relativedelta
from stockstats import wrap

from tradingagents.dataflows.errors import NoMarketDataError

from .ohlcv import load_ohlcv
from .symbols import ashare_code, ashare_exchange, normalize_ashare

logger = logging.getLogger(__name__)


def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """OHLCV rows between two dates, as a formatted CSV with a summary header."""
    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")
    canonical = normalize_ashare(symbol)

    data = load_ohlcv(symbol, end_date, fill_gaps=False)
    data = data[(data["Date"] >= pd.to_datetime(start_date)) & (data["Date"] <= pd.to_datetime(end_date))]
    if data.empty:
        raise NoMarketDataError(symbol, canonical, f"no rows between {start_date} and {end_date}")

    data = data.copy()
    for col in ("Open", "High", "Low", "Close"):
        if col in data.columns:
            data[col] = data[col].round(2)
    data["Date"] = data["Date"].dt.strftime("%Y-%m-%d")

    label = canonical if canonical == symbol.upper() else f"{canonical} (from {symbol})"
    header = f"# Stock data for {label} from {start_date} to {end_date}\n"
    header += f"# Total records: {len(data)}\n\n"
    return header + data.to_csv(index=False)


# The indicator descriptions are shared with the Yahoo path so the analyst sees
# identical guidance regardless of which vendor priced the instrument.
_INDICATOR_DESCRIPTIONS = {
    "close_50_sma": "50 SMA: medium-term trend; dynamic support/resistance.",
    "close_200_sma": "200 SMA: long-term trend benchmark; golden/death cross.",
    "close_10_ema": "10 EMA: responsive short-term average for momentum shifts.",
    "macd": "MACD: momentum via EMA differences; crossovers and divergence.",
    "macds": "MACD Signal: EMA smoothing of MACD; crossover triggers.",
    "macdh": "MACD Histogram: gap between MACD and its signal; strength.",
    "rsi": "RSI: momentum, overbought/oversold (70/30); divergence.",
    "boll": "Bollinger Middle: 20 SMA, basis for Bollinger Bands.",
    "boll_ub": "Bollinger Upper Band: +2 std; potential overbought.",
    "boll_lb": "Bollinger Lower Band: -2 std; potential oversold.",
    "atr": "ATR: average true range, volatility; stops and position sizing.",
    "vwma": "VWMA: volume-weighted moving average.",
    "mfi": "MFI: money flow index, volume-weighted RSI.",
}


def get_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    as_of_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """One indicator's daily values over a look-back window, computed locally."""
    if indicator not in _INDICATOR_DESCRIPTIONS:
        raise ValueError(
            f"Indicator {indicator} is not supported. Please choose from: {list(_INDICATOR_DESCRIPTIONS)}"
        )

    end_date = as_of_date
    as_of_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
    before = as_of_dt - relativedelta(days=look_back_days)

    indicator_data = _get_stock_stats_bulk(symbol, indicator, as_of_date)

    current_dt = as_of_dt
    date_values = []
    while current_dt >= before:
        date_str = current_dt.strftime("%Y-%m-%d")
        value = indicator_data.get(date_str, "N/A: Not a trading day (weekend or holiday)")
        date_values.append((date_str, value))
        current_dt = current_dt - relativedelta(days=1)

    ind_string = "".join(f"{d}: {v}\n" for d, v in date_values)
    result_str = (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {end_date}:\n\n"
        + ind_string
        + "\n\n"
        + _INDICATOR_DESCRIPTIONS.get(indicator, "No description available.")
    )
    return result_str


def _get_stock_stats_bulk(symbol: str, indicator: str, as_of_date: str) -> dict:
    """Compute one indicator for every available date off the A-share OHLCV frame."""
    data = load_ohlcv(symbol, as_of_date)
    df = wrap(data)
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    df[indicator]  # triggers stockstats to compute the indicator

    result = {}
    for _, row in df.iterrows():
        value = row[indicator]
        result[row["Date"]] = "N/A" if pd.isna(value) else str(value)
    return result


# Shanghai/Shenzhen composite indices, addressed the way this vendor's callers
# spell A-share benchmarks (``000001.SH`` / ``399001.SZ``). akshare's sina index
# endpoint wants the ``sh``/``sz``-prefixed code instead.
_ASHARE_INDEX_PREFIX = {"SH": "sh", "SZ": "sz"}


def _is_ashare_index(symbol: str) -> bool:
    """Whether ``symbol`` is a mainland index this vendor can price."""
    try:
        return ashare_code(symbol) in ("000001", "399001", "399006", "000300") and ashare_exchange(symbol) in ("SH", "SZ")
    except ValueError:
        return False


def get_closes(symbol: str, start_date: str, end_date: str) -> pd.Series:
    """Daily closes from ``start_date`` up to, not including, ``end_date``.

    Serves both A-share equities (via the OHLCV chain) and the two composite
    indices used as A-share benchmarks (via akshare's index endpoint), so the
    settlement path can score mainland decisions against a mainland baseline.
    Returns an empty Series on any failure, matching the Yahoo loader's contract.
    """
    try:
        if _is_ashare_index(symbol):
            import akshare as ak

            df = ak.stock_zh_index_daily(symbol=f"{_ASHARE_INDEX_PREFIX[ashare_exchange(symbol)]}{ashare_code(symbol)}")
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            s = df.dropna(subset=["date"]).set_index("date")["close"].astype(float)
        else:
            df = load_ohlcv(symbol, end_date, fill_gaps=False)
            s = df.set_index("Date")["Close"].astype(float)
        s = s[(s.index >= pd.to_datetime(start_date)) & (s.index < pd.to_datetime(end_date))]
        return s
    except Exception as e:
        logger.warning("ashare get_closes failed for %s: %s", symbol, e)
        return pd.Series(dtype=float)
