"""The analysis input form.

Derived from TradingAgents-CN's Apache-2.0-licensed
``web/components/analysis_form.py`` (session persistence, activity logging
and the inert script injection removed; analyst set extended to surgo's six).
Copyright 2024-2026 hsliuping & TradingAgents-CN Contributors
Modifications for surgo: Copyright 2026 surgo contributors
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import date as date_cls

import streamlit as st

# label → (analyst key, description, applies to A股?)
_ANALYSTS = [
    ("📈 市场技术分析师", "market", "技术指标与趋势", True),
    ("💰 基本面分析师", "fundamentals", "财务三表与估值（A 股为公告口径）", True),
    ("📰 新闻分析师", "news", "个股与宏观新闻", True),
    ("💭 情绪分析师", "social", "社交情绪（A 股社交源不可用，将降级为新闻情绪）", True),
    ("🇨🇳 大盘分析师", "index", "A 股大盘环境（仅对 A 股标的产出）", True),
    ("🏭 板块分析师", "sector", "A 股行业板块轮动（仅对 A 股标的产出）", True),
]


def render_analysis_form() -> dict:
    """Collect one analysis request. Returns {'submitted': bool, ...form fields}."""
    with st.form("analysis_form"):
        st.subheader("📊 股票分析配置")

        market_type = st.selectbox(
            "市场类型",
            options=["A股", "美股", "港股"],
            index=0,
            help="决定代码归一化规则；A 股走 surgo 的 A 股数据链路",
        )

        default_symbol = {
            "A股": "600519",
            "美股": "AAPL",
            "港股": "0700",
        }[market_type]
        stock_symbol = st.text_input(
            "股票代码",
            value=st.session_state.get("last_symbol", default_symbol),
            placeholder=default_symbol,
            key=f"symbol_input_{market_type}",
            help="A股: 6 位代码或 600519.SH；美股: AAPL；港股: 0700 或 0700.HK",
        )

        analysis_date = st.date_input(
            "分析日期",
            value=date_cls.today(),
            help="point-in-time 基准日：报告只见该日及之前的数据",
        )

        research_depth = st.select_slider(
            "研究深度",
            options=[1, 2, 3, 4, 5],
            value=st.session_state.get("last_depth", 3),
            format_func=lambda v: {1: "1 · 快速", 2: "2 · 较快", 3: "3 · 标准", 4: "4 · 深入", 5: "5 · 深度"}[v],
        )

        st.markdown("**选择分析师**")
        default_set = set(st.session_state.get("last_analysts", ["market", "news", "fundamentals"]))
        cols = st.columns(2)
        selected = []
        for i, (label, key, desc, _) in enumerate(_ANALYSTS):
            with cols[i % 2]:
                if st.checkbox(label, value=key in default_set, key=f"analyst_{key}", help=desc):
                    selected.append(key)

        submitted = st.form_submit_button("🚀 开始分析", use_container_width=True, type="primary")

    if not submitted:
        return {"submitted": False}
    if not str(stock_symbol).strip():
        st.error("请输入股票代码")
        return {"submitted": False}
    if not selected:
        st.warning("未选择任何分析师——将按默认四分析师运行")
        selected = ["market", "social", "news", "fundamentals"]

    form_data = {
        "submitted": True,
        "stock_symbol": str(stock_symbol).strip(),
        "market_type": market_type,
        "analysis_date": analysis_date.strftime("%Y-%m-%d"),
        "analysts": selected,
        "research_depth": int(research_depth),
    }
    st.session_state["last_symbol"] = form_data["stock_symbol"]
    st.session_state["last_depth"] = form_data["research_depth"]
    st.session_state["last_analysts"] = selected
    return form_data
