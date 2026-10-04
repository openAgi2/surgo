"""Sidebar: LLM configuration and run environment status.

Structure derived from TradingAgents-CN's Apache-2.0-licensed
``web/components/sidebar.py`` (multi-provider hardcoded model catalogs
replaced with surgo's own ``model_catalog``; login/permission block removed;
configuration is session-scoped — the persistent source of truth is .env /
TRADINGAGENTS_* variables, shown read-only here).
Copyright 2024-2026 hsliuping & TradingAgents-CN Contributors
Modifications for surgo: Copyright 2026 surgo contributors
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import streamlit as st

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.model_catalog import get_model_options
from web.utils.api_checker import check_api_keys, get_api_key_status_message


def _provider_names() -> list[str]:
    from cli.prompts import _llm_provider_table

    return [key for _, key, _ in _llm_provider_table()]


def _model_pick(provider: str, mode: str, current: str) -> str:
    """A selectbox over surgo's catalog, falling back to free-text custom."""
    options = get_model_options(provider, mode)
    labels = {value: label for label, value in options}
    default = current if current in labels else (
        "custom" if any(v == "custom" for _, v in options) else options[0][1]
    )
    label = labels.get(default, "Custom model ID")
    pick = st.selectbox(
        f"{mode == 'quick' and '快速' or '深度'}思考模型",
        options=[lab for lab, _ in options],
        index=[lab for lab, _ in options].index(label),
        key=f"sb_model_{mode}",
    )
    value = next(v for lab, v in options if lab == pick)
    if value == "custom":
        return st.text_input("自定义模型 ID", value=current, key=f"sb_custom_{mode}")
    return value


def render_sidebar() -> dict:
    """Render config sidebar; returns the engine-facing config values."""
    st.sidebar.title("⚙️ surgo 控制台")

    # -- LLM 配置（本次会话覆盖；持久配置走 .env） ----------------------------
    with st.sidebar.expander("🧠 LLM 配置", expanded=True):
        providers = _provider_names()
        current_provider = st.session_state.get("sb_provider", DEFAULT_CONFIG["llm_provider"])
        if current_provider not in providers:
            providers = [current_provider, *providers]
        provider = st.selectbox("LLM 提供商", providers,
                                index=providers.index(current_provider), key="sb_provider")

        quick = _model_pick(provider, "quick", st.session_state.get(
            "sb_quick_model", DEFAULT_CONFIG["quick_think_llm"]))
        deep = _model_pick(provider, "deep", st.session_state.get(
            "sb_deep_model", DEFAULT_CONFIG["deep_think_llm"]))
        backend = st.text_input(
            "API 端点（backend_url）",
            value=st.session_state.get("sb_backend", DEFAULT_CONFIG.get("backend_url") or ""),
            key="sb_backend",
            help="留空用该提供商默认端点；.env 里的 TRADINGAGENTS_LLM_BACKEND_URL 是持久配置",
        )
        st.session_state["sb_quick_model"] = quick
        st.session_state["sb_deep_model"] = deep

        if provider != DEFAULT_CONFIG["llm_provider"] or quick != DEFAULT_CONFIG["quick_think_llm"]:
            st.caption("⚠️ 以上为本次会话的覆盖值；持久配置请写入 .env（TRADINGAGENTS_*）")

    # -- API key 状态 ----------------------------------------------------------
    with st.sidebar.expander("🔑 API Key 状态", expanded=False):
        status = check_api_keys(provider)
        st.markdown(get_api_key_status_message(provider))
        for var, info in status["details"].items():
            mark = "✅" if info["configured"] else "❌"
            req = "必填" if info["required"] else "可选"
            st.caption(f"{mark} `{var}`（{req}）{info['description']}")

    # -- 系统信息 ---------------------------------------------------------------
    with st.sidebar.expander("ℹ️ 系统信息", expanded=False):
        try:
            from tradingagents import __version__
        except ImportError:
            __version__ = "?"
        st.caption(f"surgo v{__version__}")
        st.caption(f"报告目录: `{DEFAULT_CONFIG['results_dir']}`")
        st.caption(f"缓存目录: `{DEFAULT_CONFIG['data_cache_dir']}`")

    return {
        "llm_provider": provider,
        "llm_model": quick,
        "deep_model": deep,
        "backend_url": backend or None,
    }
