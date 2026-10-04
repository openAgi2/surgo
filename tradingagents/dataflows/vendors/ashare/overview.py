"""A-share broad-market overview data for the index analyst.

Provides the data the Index Analyst pre-fetches: major A-share index
performance, sector-level summary, and market breadth indicators.
All sources are tokenless and reach the developer machine without proxies.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .symbols import is_ashare

logger = logging.getLogger(__name__)

# The five major A-share indices the index analyst reports on, keyed by the
# canonical code this vendor uses. ``get_closes`` can price all of them.
_MAJOR_INDICES = {
    "000001.SH": "上证指数 (SSE Composite)",
    "399001.SZ": "深证成指 (SZSE Component)",
    "399006.SZ": "创业板指 (ChiNext)",
    "000300.SH": "沪深300 (CSI 300)",
    "000905.SH": "中证500 (CSI 500)",
}


def get_market_overview(symbol: str, trade_date: str) -> str:
    """Assemble a broad-market data block for the Index Analyst.

    For A-share symbols only.  Returns a structured text block with:
    - major index recent closes and % change
    - sector spot summary (THS industry boards)

    Returns a coverage-gap or not-applicable sentinel for non-A-share symbols.
    """
    if not is_ashare(symbol):
        return (
            "<market_overview_unavailable>\n"
            "Broad-market A-share indices are not applicable to this instrument.\n"
            "</market_overview_unavailable>"
        )

    parts: list[str] = []

    # --- Major index performance ---------------------------------------------------
    index_block = _fetch_index_performance(trade_date)
    if index_block:
        parts.append(index_block)

    # --- THS industry board snapshot -----------------------------------------------
    sector_block = _fetch_sector_snapshot()
    if sector_block:
        parts.append(sector_block)

    if not parts:
        return (
            "<market_overview_unavailable>\n"
            "Could not retrieve A-share market overview data.\n"
            "</market_overview_unavailable>"
        )

    return "\n\n".join(parts)


def _fetch_index_performance(trade_date: str) -> str:
    """Recent closes for the five major A-share indices.

    Looks back 30 calendar days (roughly 22 trading days) and reports the
    last close, the close 5 and 20 sessions prior, and simple % changes.
    """
    as_of = datetime.strptime(trade_date, "%Y-%m-%d")
    lookback = (as_of - timedelta(days=45)).strftime("%Y-%m-%d")
    end = trade_date

    rows: list[str] = []
    for code, label in _MAJOR_INDICES.items():
        try:
            from .market import get_closes  # avoid circular at module level

            s = get_closes(code, lookback, end)
            if s.empty:
                rows.append(f"| {label} | — | — | — | — |")
                continue
            s = s.sort_index()
            current = s.iloc[-1]
            chg_5d = ((current / s.iloc[-6]) - 1) * 100 if len(s) >= 6 else None
            chg_20d = ((current / s.iloc[-21]) - 1) * 100 if len(s) >= 21 else None
            c5 = f"{chg_5d:+.2f}%" if chg_5d is not None else "—"
            c20 = f"{chg_20d:+.2f}%" if chg_20d is not None else "—"
            rows.append(f"| {label} | {current:,.2f} | {c5} | {c20} |")
        except Exception as exc:
            logger.debug("index performance fetch failed for %s: %s", code, exc)
            rows.append(f"| {label} | — | — | — |")

    if all("—" in r for r in rows):
        return ""

    header = (
        "## Major A-share Index Performance\n\n"
        "Latest close as of the analysis date, with 5-trading-day and "
        "20-trading-day percentage changes.\n\n"
        "| Index | Latest Close | 5D Change | 20D Change |\n"
        "|---|---:|---:|---:|\n"
    )
    return header + "\n".join(rows)


def _fetch_sector_snapshot() -> str:
    """Top and bottom THS industry boards by today's change.

    Uses ``stock_board_industry_name_ths`` (list of 90 boards) and
    ``stock_board_industry_info_ths`` (per-board snapshot).  Fetches a
    sample of boards; on any failure returns an empty string.
    """
    try:
        import akshare as ak

        # Get the list of industry boards
        boards = ak.stock_board_industry_name_ths()
        if boards is None or boards.empty:
            return ""

        # Sample up to 20 boards (avoid hammering the API for all 90)
        sample_names = boards["name"].tolist()[:20]

        board_data: list[dict] = []
        for name in sample_names:
            try:
                info = ak.stock_board_industry_info_ths(symbol=name)
                if info is not None and not info.empty:
                    info_dict = dict(zip(info["项目"], info["值"], strict=True))
                    board_data.append({
                        "name": name,
                        "change": info_dict.get("板块涨幅", "—"),
                        "rank": info_dict.get("涨幅排名", "—"),
                        "net_flow": info_dict.get("资金净流入(亿)", "—"),
                    })
            except Exception:
                continue

        if not board_data:
            return ""

        # Sort by change (parse percentage strings)
        def _parse_pct(v):
            try:
                return float(str(v).replace("%", ""))
            except (ValueError, TypeError):
                return 0.0

        board_data.sort(key=lambda b: _parse_pct(b["change"]), reverse=True)

        lines = [
            "## THS Industry Board Snapshot (sample)\n",
            "| Board | Change | Rank | Net Flow (¥B) |",
            "|---|---:|---:|---:|",
        ]
        for b in board_data[:15]:
            lines.append(
                f"| {b['name']} | {b['change']} | {b['rank']} | {b['net_flow']} |"
            )

        return "\n".join(lines)

    except Exception as exc:
        logger.debug("sector snapshot fetch failed: %s", exc)
        return ""
