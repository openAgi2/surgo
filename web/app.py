"""surgo web UI main application.

Streamlit entry point: sidebar config → analysis form → background-thread
run with live progress → results.

Derived from TradingAgents-CN's Apache-2.0-licensed ``web/app.py``
(historical revision 5a143f44^): the analysis pipeline skeleton, CSS chrome
and background-thread + progress-file architecture are carried over; the
login/permission gate, admin pages, frontend auth-cache JS, Redis/MongoDB
persistence and activity logging are cut for this single-user port.
Copyright 2024-2026 hsliuping & TradingAgents-CN Contributors
Modifications for surgo: Copyright 2026 surgo contributors
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import threading
import time

import streamlit as st

from web.components.analysis_form import render_analysis_form
from web.components.header import render_header
from web.components.results_display import render_results
from web.components.sidebar import render_sidebar
from web.utils.analysis_runner import run_stock_analysis
from web.utils.async_progress_tracker import (
    AsyncProgressTracker,
    get_progress_by_id,
    new_analysis_id,
)

st.set_page_config(page_title="Surgo 交易分析", page_icon="🎯", layout="wide")

# --- global CSS (carried over from the CN app's chrome, re-skinned) --------
st.markdown(
    """
    <style>
        /* hide streamlit chrome */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header[data-testid="stHeader"] {background: transparent;}

        .main-header {
            background: linear-gradient(135deg, #1a237e 0%, #283593 60%, #3949ab 100%);
            color: white;
            padding: 1.2rem 1.6rem;
            border-radius: 0.8rem;
            margin-bottom: 1rem;
        }
        .main-header h1 {margin: 0; font-size: 1.6rem; color: white;}
        .main-header p {margin: 0.3rem 0 0 0; opacity: 0.85;}

        section[data-testid="stSidebar"] {width: 320px;}

        .stTabs [data-baseweb="tab-list"] {gap: 0.4rem;}
        .stTabs [data-baseweb="tab"] {border-radius: 0.4rem 0.4rem 0 0; padding: 0.4rem 0.9rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def _initialize_session_state():
    defaults = {
        "current_analysis_id": None,
        "show_results": False,
        "last_results": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _spawn_analysis(form_data: dict, sidebar_cfg: dict):
    """Start one analysis on a daemon thread; UI polls the progress file."""
    analysis_id = new_analysis_id()
    tracker = AsyncProgressTracker(analysis_id, form_data["analysts"])
    st.session_state["current_analysis_id"] = analysis_id
    st.session_state["show_results"] = False
    st.session_state["last_results"] = None

    form = dict(form_data)
    form["_tracker"] = tracker

    def worker():
        try:
            results = run_stock_analysis(
                form,
                llm_provider=sidebar_cfg["llm_provider"],
                llm_model=sidebar_cfg["llm_model"],
                deep_model=sidebar_cfg.get("deep_model"),
                backend_url=sidebar_cfg.get("backend_url"),
                progress_callback=lambda message, stage=None: tracker.update_progress(
                    message=message, stage=stage
                ),
                output_language=sidebar_cfg.get("output_language", "English"),
            )
            tracker.mark_completed(results)
        except Exception as exc:  # never leave the tracker stuck in "running"
            tracker.mark_failed(str(exc))

    threading.Thread(target=worker, name=f"analysis-{analysis_id}", daemon=True).start()


def _render_progress(analysis_id: str):
    """Poll and render live progress; hand off to results on completion."""
    p = get_progress_by_id(analysis_id)
    if p is None:
        st.warning("找不到该分析的进度记录")
        st.session_state["current_analysis_id"] = None
        return

    status = p.get("status")
    pct = int(p.get("progress_percentage") or 0)
    elapsed = p.get("elapsed_time") or 0

    if status == "running":
        st.progress(min(pct, 95) / 100)
        st.markdown(
            f"**{p.get('stage_label', '')}** — {p.get('last_message', '')}"
            f"　·　LLM 调用 {p.get('llm_calls', 0)} 次（预估 "
            f"{p.get('estimated_llm_calls', '?')} 次）　·　已运行 {elapsed:.0f}s"
        )
        time.sleep(2)
        st.rerun()
    elif status == "failed":
        st.error(f"分析失败: {p.get('error', '未知错误')}")
        if st.button("清除并重新开始"):
            st.session_state["current_analysis_id"] = None
            st.rerun()
    elif status == "completed":
        results = p.get("raw_results")
        st.session_state["last_results"] = results
        st.session_state["show_results"] = True
        st.session_state["current_analysis_id"] = None
        st.rerun()


def main():
    _initialize_session_state()
    render_header()
    sidebar_cfg = render_sidebar()

    # -- in-flight or completed run wins the main area -------------------------
    if st.session_state.get("current_analysis_id"):
        with st.container():
            _render_progress(st.session_state["current_analysis_id"])
        return

    if st.session_state.get("show_results") and st.session_state.get("last_results"):
        results = st.session_state["last_results"]
        left, _ = st.columns([5, 1])
        with left:
            if st.button("← 返回新建分析"):
                st.session_state["show_results"] = False
                st.session_state["last_results"] = None
                st.rerun()
        render_results(results)
        return

    # -- fresh page: form + short usage guide -----------------------------------
    form_col, guide_col = st.columns([3, 2])
    with form_col:
        form_data = render_analysis_form()
        if form_data.get("submitted"):
            _spawn_analysis(form_data, sidebar_cfg)
            st.rerun()
    with guide_col:
        with st.expander("📖 使用指南", expanded=True):
            st.markdown(
                """
                1. 侧边栏确认 LLM 配置（持久配置写 `.env`）
                2. 选择市场、输入代码、选分析师
                3. 点击 **开始分析**，等待 2–10 分钟
                4. 查看 9 个报告页签，下载 Markdown/JSON

                **分析师说明**
                - 🇨🇳 大盘 / 🏭 板块分析师仅对 A 股标的产出报告
                - 💭 情绪分析师对 A 股降级为新闻情绪（无中文社交源）
                - 分析日期是 point-in-time 基准：历史日期只见当日及之前的数据
                - 新闻源为滚动窗口：太久远的日期会如实报告数据不可得
                """
            )
        with st.expander("⚠️ 免责声明"):
            st.caption(
                "本工具产出的是研究参考，不构成投资建议。所有数据按 point-in-time "
                "纪律获取，但模型输出可能出错，决策前请自行核实。"
            )


main()
