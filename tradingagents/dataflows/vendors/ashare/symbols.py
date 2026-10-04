"""A-share ticker detection and normalization.

Mainland Chinese equities trade on three exchanges, each with a distinct code
series and a preferred spelling per upstream data source:

    series      exchange   tushare      baostock    sina/tencent   yahoo
    ----------  ---------  -----------  ----------  -------------  --------
    600/601/603/605  SSE    600519.SH    sh.600519   sh600519       600519.SS
    688 (STAR)       SSE    688981.SH    sh.688981   sh688981       688981.SS
    000/001/002/003  SZSE   000001.SZ    sz.000001   sz000001       000001.SZ
    300 (ChiNext)    SZSE   300750.SZ    sz.300750   sz300750       300750.SZ
    4xx/8xx/920      BSE    920001.BJ    bj.920001   bj920001       (none)

The broker/CLI spellings vary — ``600519``, ``600519.SH``, ``600519.SS``,
``sh600519``, ``sh.600519`` all mean the same instrument. This module is the
single place that recognizes them and renders each upstream's preferred form.
Purely syntactic, no network calls.
"""

from __future__ import annotations

import re

# Accepts the common spellings of a mainland A-share code and captures the six
# digits plus an optional exchange hint. The hint is honored when present; when
# absent the exchange is inferred from the code series.
_ASHARE_RE = re.compile(
    r"^(?:(?P<prefix>sh|sz|bj)[\.]?)?(?P<code>\d{6})(?:[\.]?(?P<suffix>sh|ss|sz|bj))?$",
    re.IGNORECASE,
)


def _exchange_from_series(code: str) -> str:
    """Infer the exchange from a six-digit code's leading digits.

    Returns one of ``"SH"`` (Shanghai), ``"SZ"`` (Shenzhen), ``"BJ"`` (Beijing).
    Defaults to ``"SH"`` only for series that are unambiguous; an unrecognized
    series raises ``ValueError`` so a mistyped code is not silently mis-routed.
    """
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return "SH"
    if code.startswith(("000", "001", "002", "003", "300", "301")):
        return "SZ"
    if code.startswith(("4", "8", "920")):
        return "BJ"
    raise ValueError(f"unrecognized A-share code series: {code!r}")


def is_ashare(symbol: str) -> bool:
    """Whether ``symbol`` parses as a mainland A-share code."""
    if not isinstance(symbol, str) or not symbol.strip():
        return False
    return _ASHARE_RE.match(symbol.strip()) is not None


def ashare_exchange(symbol: str) -> str:
    """Return the exchange for an A-share symbol: ``SH`` / ``SZ`` / ``BJ``."""
    m = _ASHARE_RE.match(symbol.strip()) if isinstance(symbol, str) else None
    if not m:
        raise ValueError(f"not an A-share symbol: {symbol!r}")
    code = m.group("code")
    hint = (m.group("prefix") or m.group("suffix") or "").upper()
    if hint:
        # Yahoo spells Shanghai ".SS"; treat it the same as ".SH".
        return "SH" if hint == "SS" else hint
    return _exchange_from_series(code)


def ashare_code(symbol: str) -> str:
    """Return just the six-digit A-share code (e.g. ``600519``)."""
    m = _ASHARE_RE.match(symbol.strip()) if isinstance(symbol, str) else None
    if not m:
        raise ValueError(f"not an A-share symbol: {symbol!r}")
    return m.group("code")


def normalize_ashare(symbol: str) -> str:
    """Canonical surgo form: ``600519.SH`` / ``000001.SZ`` / ``920001.BJ``.

    Uses tushare's ``.SH`` spelling for Shanghai (not Yahoo's ``.SS``), since
    this vendor never routes to Yahoo and ``.SH`` is the unambiguous exchange
    code. Raises ``ValueError`` for non-A-share symbols.
    """
    return f"{ashare_code(symbol)}.{ashare_exchange(symbol)}"


def to_tushare(symbol: str) -> str:
    """tushare ``ts_code`` form: ``600519.SH`` (Shanghai is ``.SH``)."""
    return normalize_ashare(symbol)


def to_baostock(symbol: str) -> str:
    """baostock code form: ``sh.600519`` (lowercase exchange prefix)."""
    return f"{ashare_exchange(symbol).lower()}.{ashare_code(symbol)}"


def to_sina(symbol: str) -> str:
    """sina/tencent code form: ``sh600519`` (lowercase, no separator)."""
    return f"{ashare_exchange(symbol).lower()}{ashare_code(symbol)}"
