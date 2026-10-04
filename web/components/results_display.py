"""Live-run results renderer.

Renders the results envelope produced by ``web.utils.analysis_runner``:
decision summary (rating + price target extracted from the engine's own
decision text), config info, one tab per non-empty report, and download
buttons backed by surgo's native report tree.

Derived from TradingAgents-CN's Apache-2.0-licensed
``web/components/results_display.py`` (dead chart code, debug widgets and
CN provider display maps removed; state-key list extended with surgo's
index/sector reports; decision cards re-pointed at surgo's plain-string
rating — no synthetic confidence or risk scores).
Copyright 2024-2026 hsliuping & TradingAgents-CN Contributors
Modifications for surgo: Copyright 2026 surgo contributors
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from web.utils.analysis_runner import extract_price_target

# (state key, tab label) — one tab per non-empty report, canonical order.
_MODULES = [
    ("market_report", "📈 市场技术"),
    ("fundamentals_report", "💰 基本面"),
    ("news_report", "📰 新闻"),
    ("sentiment_report", "💭 情绪"),
    ("index_report", "🇨🇳 大盘环境"),
    ("sector_report", "🏭 板块"),
    ("investment_plan", "🧭 研究经理计划"),
    ("trader_investment_plan", "📋 交易员提案"),
    ("final_trade_decision", "🎯 组合经理终审"),
]

_RATING_COLOR = {
    "BUY": "green", "OVERWEIGHT": "green",
    "HOLD": "blue",
    "UNDERWEIGHT": "orange", "SELL": "red",
}


def render_results(results: dict):
    """Render a completed run's envelope."""
    if not results.get("success"):
        st.error(f"分析失败: {results.get('error', '未知错误')}")
        return

    state = results.get("state") or {}
    decision = results.get("decision")

    # -- decision summary ----------------------------------------------------
    rating = str(decision or "").strip() or "—"
    target = extract_price_target(state)

    cols = st.columns([2, 2, 2, 3])
    cols[0].metric("投资评级", rating)
    cols[1].metric("目标价", target or "—")
    cols[2].metric("耗时", f"{results.get('duration_seconds', 0):.0f}s")
    with cols[3]:
        st.caption(
            f"{results.get('llm_provider', '?')} · {results.get('llm_model', '?')} · "
            f"研究深度 {results.get('research_depth', '?')} · "
            f"分析师 {len(results.get('analysts') or [])} 个"
        )

    # -- analyst reports, one tab each ---------------------------------------
    tabs = [label for key, label in _MODULES if (state.get(key) or "").strip()]
    if not tabs:
        st.info("本次运行没有产出任何报告段")
        return
    tab_objs = st.tabs(tabs)
    for tab, (key, _label) in zip(tab_objs, [m for m in _MODULES if (state.get(m[0]) or "").strip()], strict=True):
        with tab:
            st.markdown(_first_n(state.get(key) or "", 8000))

    # -- research & risk debates (collapsed) ----------------------------------
    debate = state.get("investment_debate_state") or {}
    if debate.get("history"):
        with st.expander("⚖️ 多空研究辩论记录"):
            st.markdown(_first_n(debate["history"], 12000))
    risk = state.get("risk_debate_state") or {}
    risk_hist = risk.get("history") or "\n\n".join(
        x for x in (risk.get("aggressive_history"), risk.get("conservative_history"), risk.get("neutral_history")) if x
    )
    if risk_hist.strip():
        with st.expander("🛡️ 风险管理辩论记录"):
            st.markdown(_first_n(risk_hist, 12000))

    # -- exports ---------------------------------------------------------------
    _render_exports(results, state)


def _render_exports(results: dict, state: dict):
    st.markdown("---")
    ecols = st.columns([1, 1, 2])
    complete_md = _compose_markdown(results, state)
    ecols[0].download_button(
        "⬇️ 下载完整报告 (Markdown)",
        data=complete_md,
        file_name=f"surgo_{results.get('stock_symbol', 'report')}_{results.get('analysis_date', '')}.md",
        mime="text/markdown",
        use_container_width=True,
    )
    import json

    ecols[1].download_button(
        "⬇️ 下载结构化结果 (JSON)",
        data=json.dumps(
            {k: v for k, v in state.items() if k != "messages"}, ensure_ascii=False, default=str, indent=2
        ),
        file_name=f"surgo_{results.get('stock_symbol', 'report')}_{results.get('analysis_date', '')}.json",
        mime="application/json",
        use_container_width=True,
    )
    reports_dir = results.get("reports_dir")
    if reports_dir and Path(reports_dir).exists():
        ecols[2].caption(f"分段报告已存至: `{reports_dir}`")


def _compose_markdown(results: dict, state: dict) -> str:
    """A self-contained markdown of the run (mirrors the on-disk tree)."""
    lines = [
        f"# Surgo 分析报告: {results.get('stock_symbol', '?')}",
        f"- 分析日期: {results.get('analysis_date', '?')}",
        f"- 评级: {results.get('decision', '—')}",
        f"- 模型: {results.get('llm_provider', '?')} / {results.get('llm_model', '?')}",
        f"- 分析师: {', '.join(results.get('analysts') or [])}",
        "",
    ]
    for key, label in _MODULES:
        text = (state.get(key) or "").strip()
        if text:
            lines += [f"## {label}", "", text, ""]
    return "\n".join(lines)


def _first_n(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + f"\n\n…(截断，完整内容见下载报告，共 {len(text)} 字符)"
