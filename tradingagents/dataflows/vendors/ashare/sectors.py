"""A-share sector/industry data for the sector analyst.

Provides the data the Sector Analyst pre-fetches: the stock's THS industry
classification, sector-level performance, and sector index history.
All sources are tokenless and reachable without proxies.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from tradingagents.dataflows.vendors.ashare.symbols import is_ashare, normalize_ashare

logger = logging.getLogger(__name__)


def get_sector_info(symbol: str, trade_date: str) -> str:
    """Assemble a sector data block for the Sector Analyst.

    For A-share symbols only.  Returns a structured text block with:
    - the stock's THS industry board classification
    - the sector's recent performance snapshot
    - sector index OHLCV trend (if available)

    Returns a not-applicable sentinel for non-A-share symbols.
    """
    if not is_ashare(symbol):
        return (
            "<sector_info_unavailable>\n"
            "A-share sector analysis is not applicable to this instrument.\n"
            "</sector_info_unavailable>"
        )

    canonical = normalize_ashare(symbol)
    parts: list[str] = [f"## Sector Analysis for {canonical}\n"]

    # --- Identify the stock's sector ------------------------------------------------
    sector_name = _find_sector(canonical)
    if not sector_name:
        parts.append(
            "Could not identify the stock's THS industry board. "
            "The sector classification lookup returned no match."
        )
        return "\n".join(parts)

    parts.append(f"**THS Industry Board:** {sector_name}\n")

    # --- Sector performance snapshot ------------------------------------------------
    snapshot = _fetch_sector_snapshot(sector_name)
    if snapshot:
        parts.append(snapshot)

    # --- Sector index history -------------------------------------------------------
    index_hist = _fetch_sector_index(sector_name, trade_date)
    if index_hist:
        parts.append(index_hist)

    return "\n".join(parts)


def _find_sector(symbol: str) -> str | None:
    """Identify the stock's THS industry board.

    The constituent-stock lookup (eastmoney endpoint) is unreliable from
    this developer machine.  Instead, we:

    1. Look up the CSRC (证监会) industry name via cninfo profile.
    2. Keyword-match the CSRC name against the 90 THS industry boards.
    3. If no keyword match, fall back to scanning the sina sector spot
       data (which embeds a representative stock code per sector).

    Returns the THS board name (e.g. "白酒"), or None.
    """
    try:
        import akshare as ak

        # --- Strategy 1: cninfo profile → CSRC industry → keyword match to THS ---
        cninfo_industry = _cninfo_industry(symbol)
        if cninfo_industry:
            ths_boards = ak.stock_board_industry_name_ths()
            if ths_boards is not None and not ths_boards.empty:
                board_names = ths_boards["name"].tolist()
                # Try exact substring match: if any THS board name appears
                # inside the CSRC industry name, that's our sector.
                for board in board_names:
                    if board in cninfo_industry:
                        return board
                # Reverse: if the CSRC industry name appears inside a THS
                # board name (less common but possible).
                for board in board_names:
                    if cninfo_industry in board:
                        return board
                # Fuzzy match: split the cninfo industry by "、" and check
                # if any THS board contains one of the fragments.  E.g.
                # cninfo "酒、饮料和精制茶制造业" → fragments ["酒", "饮料和精制茶制造业"]
                # → "白酒" contains "酒" → match; "饮料制造" contains "饮料" → also match.
                # Prefer the shortest board name among matches (most specific).
                fragments = [f.strip() for f in cninfo_industry.replace("和", "、").split("、") if f.strip()]
                matches: list[str] = []
                for frag in fragments:
                    for board in board_names:
                        if frag in board:
                            matches.append(board)
                if matches:
                    return min(matches, key=len)

                # If no fragment-level match, try the company's main business
                # description from cninfo.  E.g. CATL's CSRC industry is the
                # broad "电气机械和器材制造业", but its main business mentions
                # "电池", which directly maps to the THS "电池" board.
                main_biz = _cninfo_main_business(symbol)
                if main_biz:
                    for board in board_names:
                        if board in main_biz:
                            matches.append(board)
                    if matches:
                        return min(matches, key=len)

        # --- Strategy 2: sina sector spot data ---
        try:
            spot = ak.stock_sector_spot(indicator="新浪行业")
            if spot is not None and not spot.empty:
                code6 = symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
                match = spot[spot["股票代码"].str.contains(code6, na=False)]
                if not match.empty:
                    return match.iloc[0]["板块"]
        except Exception as exc:
            logger.debug("sina sector spot lookup failed: %s", exc)

        return None

    except Exception as exc:
        logger.debug("sector identification failed for %s: %s", symbol, exc)
        return None


def _cninfo_industry(symbol: str) -> str | None:
    """Look up the CSRC industry classification from cninfo profile.

    Returns the industry string (e.g. "酒、饮料和精制茶制造业"), or None.
    """
    try:
        import akshare as ak

        code6 = normalize_ashare(symbol).split(".")[0]
        prof = ak.stock_profile_cninfo(symbol=code6)
        if prof is not None and not prof.empty:
            row = prof.iloc[0]
            industry = row.get("所属行业")
            if industry and str(industry).strip():
                return str(industry).strip()
    except Exception as exc:
        logger.debug("cninfo industry lookup failed for %s: %s", symbol, exc)
    return None


def _cninfo_main_business(symbol: str) -> str | None:
    """Look up the main business description from cninfo profile.

    Returns the description string, or None.  Used as a fallback to
    match stocks to THS industry boards when the CSRC industry name
    is too broad.
    """
    try:
        import akshare as ak

        code6 = normalize_ashare(symbol).split(".")[0]
        prof = ak.stock_profile_cninfo(symbol=code6)
        if prof is not None and not prof.empty:
            row = prof.iloc[0]
            biz = row.get("主营业务")
            if biz and str(biz).strip():
                return str(biz).strip()
    except Exception as exc:
        logger.debug("cninfo main business lookup failed for %s: %s", symbol, exc)
    return None


def _fetch_sector_snapshot(sector_name: str) -> str:
    """THS industry board snapshot for a named sector."""
    try:
        import akshare as ak

        info = ak.stock_board_industry_info_ths(symbol=sector_name)
        if info is None or info.empty:
            return ""

        info_dict = dict(zip(info["项目"], info["值"], strict=True))
        lines = [
            f"### {sector_name} Sector Snapshot\n",
        ]
        for key, val in info_dict.items():
            lines.append(f"- **{key}**: {val}")
        return "\n".join(lines)

    except Exception as exc:
        logger.debug("sector snapshot failed for %s: %s", sector_name, exc)
        return ""


def _fetch_sector_index(sector_name: str, trade_date: str) -> str:
    """THS industry board index OHLCV for the last 30 trading days."""
    try:
        import akshare as ak

        df = ak.stock_board_industry_index_ths(symbol=sector_name)
        if df is None or df.empty:
            return ""

        # Filter to the lookback window
        as_of = datetime.strptime(trade_date, "%Y-%m-%d")
        cutoff = (as_of - timedelta(days=60)).strftime("%Y-%m-%d")
        df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
        df = df[df["日期"] <= as_of]
        df = df[df["日期"] >= cutoff]

        if df.empty:
            return ""

        # Show last 10 rows for compactness
        recent = df.tail(10).copy()
        recent["日期"] = recent["日期"].dt.strftime("%Y-%m-%d")

        header = (
            f"\n### {sector_name} Index (recent 10 sessions)\n\n"
            "| Date | Open | High | Low | Close | Volume |\n"
            "|---|---:|---:|---:|---:|---:|\n"
        )
        rows = []
        for _, r in recent.iterrows():
            rows.append(
                f"| {r['日期']} | {r['开盘价']:.2f} | {r['最高价']:.2f} "
                f"| {r['最低价']:.2f} | {r['收盘价']:.2f} | {r['成交量']:,.0f} |"
            )

        # Add a trend summary
        if len(df) >= 5:
            latest = df.iloc[-1]["收盘价"]
            five_ago = df.iloc[-5]["收盘价"]
            chg = ((latest / five_ago) - 1) * 100
            trend = f"\n**5-session trend:** {chg:+.2f}%"
        else:
            trend = ""

        return header + "\n".join(rows) + trend

    except Exception as exc:
        logger.debug("sector index fetch failed for %s: %s", sector_name, exc)
        return ""
