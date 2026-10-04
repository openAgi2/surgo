"""Page header.

Derived from TradingAgents-CN's Apache-2.0-licensed
``web/components/header.py`` (branding re-skinned for surgo).
Copyright 2024-2026 hsliuping & TradingAgents-CN Contributors
Modifications for surgo: Copyright 2026 surgo contributors
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import streamlit as st


def render_header():
    st.markdown(
        """
        <div class="main-header">
            <h1>🎯 Surgo 多智能体交易分析</h1>
            <p>A 股 / 美股 / 港股 · 多智能体辩论 · point-in-time 数据</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    cols[0].metric("🤖 协作智能体", "12+")
    cols[1].metric("📊 分析师", "6 类")
    cols[2].metric("🇨🇳 A 股数据", "直连")
    cols[3].metric("⏱️ PIT 纪律", "严格")
    st.markdown("---")
