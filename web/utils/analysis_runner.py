"""The engine seam of the surgo web UI.

Builds a surgo engine config from the form inputs, invokes
``TradingAgentsGraph(...).propagate(...)`` on the caller's thread (the app
spawns it in a background daemon thread), and returns a uniform results
envelope the UI renders.

Derived from TradingAgents-CN's Apache-2.0-licensed
``web/utils/analysis_runner.py`` (CN provider ladders, token tracking, demo
results and log-manager coupling removed; decision handling re-pointed at
surgo's plain-string rating — no synthetic confidence/risk numbers).
Copyright 2024-2026 hsliuping & TradingAgents-CN Contributors
Modifications for surgo: Copyright 2026 surgo contributors
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
import uuid

from langchain_core.callbacks import BaseCallbackHandler

from tradingagents.default_config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)

# surgo's analyst keys (web and CLI share the same wire values).
SUPPORTED_ANALYSTS = ["market", "social", "news", "fundamentals", "index", "sector"]

# research_depth 1-5 → debate-round settings (same ladder the CN UI used).
_DEPTH_ROUNDS = {
    1: (1, 1),
    2: (1, 1),
    3: (1, 2),
    4: (2, 2),
    5: (3, 3),
}


def validate_analysis_params(form_data: dict) -> tuple[bool, str]:
    symbol = str(form_data.get("stock_symbol", "")).strip()
    if not symbol:
        return False, "请输入股票代码"
    analysts = form_data.get("analysts") or []
    unknown = [a for a in analysts if a not in SUPPORTED_ANALYSTS]
    if unknown:
        return False, f"未知分析师: {', '.join(unknown)}；可选: {', '.join(SUPPORTED_ANALYSTS)}"
    if not analysts:
        return False, "请至少选择一个分析师"
    date = str(form_data.get("analysis_date", "")).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return False, f"分析日期格式应为 YYYY-MM-DD，收到: {date!r}"
    return True, ""


def normalize_symbol(symbol: str, market_type: str) -> str:
    """Market-aware symbol normalization (carried over from the CN form logic)."""
    s = symbol.strip()
    if market_type == "A股":
        return s  # 6-digit codes pass through; the router detects the market
    if market_type == "港股":
        s = s.upper()
        return s.zfill(4) + ".HK" if s.isdigit() else s
    return s.upper()  # 美股


class _LLMCallCounter(BaseCallbackHandler):
    """LangChain callback that counts LLM calls into the progress tracker."""

    def __init__(self, tracker):
        super().__init__()
        self._tracker = tracker

    def on_llm_start(self, serialized, prompts, **kwargs):
        with contextlib.suppress(Exception):
            self._tracker.bump_llm_calls()


def build_engine_config(
    llm_provider: str,
    llm_model: str,
    deep_model: str | None,
    backend_url: str | None,
    research_depth: int,
) -> dict:
    """surgo DEFAULT_CONFIG + the web form's overrides."""
    config = dict(DEFAULT_CONFIG)
    config["llm_provider"] = llm_provider
    config["quick_think_llm"] = llm_model
    config["deep_think_llm"] = deep_model or llm_model
    if backend_url:
        config["backend_url"] = backend_url
    debate, risk = _DEPTH_ROUNDS.get(int(research_depth), (1, 1))
    config["max_debate_rounds"] = debate
    config["max_risk_discuss_rounds"] = risk
    return config


def run_stock_analysis(
    form_data: dict,
    llm_provider: str,
    llm_model: str,
    deep_model: str | None = None,
    backend_url: str | None = None,
    progress_callback=None,
) -> dict:
    """Run one full surgo analysis; returns a uniform results envelope.

    ``progress_callback(message, stage)`` receives the runner's real stage
    transitions. Long-running and blocking — callers background it.
    """
    session_id = str(uuid.uuid4())[:8]

    def update(message: str, stage: str | None = None):
        if progress_callback:
            with contextlib.suppress(Exception):
                progress_callback(message, stage)

    base = {
        "stock_symbol": str(form_data.get("stock_symbol", "")).strip(),
        "analysis_date": str(form_data.get("analysis_date", "")).strip(),
        "market_type": form_data.get("market_type", "A股"),
        "analysts": list(form_data.get("analysts") or []),
        "research_depth": form_data.get("research_depth", 3),
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "session_id": session_id,
    }

    t0 = time.time()
    try:
        update("校验分析参数", "validating")
        ok, err = validate_analysis_params(form_data)
        if not ok:
            return {**base, "success": False, "error": err, "state": {}, "decision": None}

        update("初始化分析引擎", "init_engine")
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        config = build_engine_config(llm_provider, llm_model, deep_model, backend_url, base["research_depth"])
        symbol = normalize_symbol(base["stock_symbol"], base["market_type"])

        # The tracker ref (if any) powers the live LLM-call counter.
        tracker = form_data.get("_tracker")
        callbacks = [_LLMCallCounter(tracker)] if tracker is not None else None

        update(f"运行分析引擎: {symbol} @ {base['analysis_date']}", "analysing")
        graph = TradingAgentsGraph(base["analysts"], config=config, callbacks=callbacks)
        state, rating = graph.propagate(symbol, base["analysis_date"])

        update("生成报告", "reports")
        reports_dir = None
        try:
            path = graph.save_reports(state, symbol)
            reports_dir = str(path.parent) if path else None
        except Exception as exc:
            logger.warning("save_reports failed: %s", exc)

        return {
            **base,
            "success": True,
            "error": None,
            "state": state,
            "decision": rating,
            "reports_dir": reports_dir,
            "duration_seconds": round(time.time() - t0, 1),
        }

    except Exception as exc:
        logger.exception("web analysis failed")
        message = f"{type(exc).__name__}: {exc}"
        if "null value for 'choices'" in message:
            # An OpenAI-protocol endpoint answered with an error body (Zhipu's
            # gateway does this for e.g. coding-plan keys without balance on
            # the standard endpoint); the server's own reason is lost inside
            # the SDK, so point at the known configuration cause.
            message += (
                " —— 服务端返回了错误体而非补全结果。若你用的是 GLM Coding Plan "
                "套餐 key：请在侧边栏选「GLM Coding Plan」提供商（走 Anthropic "
                "兼容端点），标准 OpenAI 端点对套餐 key 不开放。"
            )
        return {
            **base,
            "success": False,
            "error": message,
            "state": {},
            "decision": None,
            "duration_seconds": round(time.time() - t0, 1),
        }


_PRICE_TARGET_RE = re.compile(
    r"\*\*Price Target\*\*\s*[:：]?\s*([^\n]+)|Price Target\s*[:：]\s*([^\n]+)"
)


def extract_price_target(state: dict) -> str | None:
    """Pull the price target out of the Portfolio Manager's decision text.

    Reads the labelled line the engine itself emitted — an extraction, not a
    fabrication; returns None when the decision text carries no such line.
    """
    text = (state or {}).get("final_trade_decision") or ""
    m = _PRICE_TARGET_RE.search(text)
    if not m:
        return None
    value = (m.group(1) or m.group(2) or "").strip().rstrip("*")
    return value or None
