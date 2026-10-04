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

# A web-side pseudo-provider: the GLM Coding Plan key only has quota on the
# Anthropic-compatible endpoint, so this choice maps to provider "anthropic"
# + that endpoint while still offering the GLM model catalog.
CODING_PLAN = "glm-coding-plan"
CODING_PLAN_BACKEND = "https://api.z.ai/api/anthropic"


def resolve_provider(choice: str) -> tuple[str, str, str | None]:
    """(engine provider, catalog provider, default backend) for a sidebar choice.

    Pure function so the mapping is testable without streamlit.
    """
    if choice == CODING_PLAN:
        return "anthropic", "glm", CODING_PLAN_BACKEND
    return choice, choice, None


def _default_provider_choice() -> str:
    """Preselect the coding-plan pseudo-provider when .env pins that setup."""
    backend = DEFAULT_CONFIG.get("backend_url") or ""
    if (
        DEFAULT_CONFIG["llm_provider"] == "anthropic"
        and "/anthropic" in backend
        and str(DEFAULT_CONFIG["quick_think_llm"]).startswith("glm-")
    ):
        return CODING_PLAN
    return DEFAULT_CONFIG["llm_provider"]


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
    from cli.prompts import _llm_provider_table

    with st.sidebar.expander("🧠 LLM 配置", expanded=True):
        engine_providers = _llm_provider_table()
        providers = [CODING_PLAN, *[key for _, key, _ in engine_providers]]
        current_provider = st.session_state.get("sb_provider", _default_provider_choice())
        if current_provider not in providers:
            providers = [current_provider, *providers]
        provider = st.selectbox(
            "LLM 提供商",
            providers,
            index=providers.index(current_provider),
            key="sb_provider",
            format_func=lambda p: "GLM Coding Plan（智谱套餐 · Anthropic 端点）" if p == CODING_PLAN else p,
        )
        engine_provider, catalog_provider, default_backend = resolve_provider(provider)

        if provider in ("glm", "glm-cn"):
            st.caption(
                "⚠️ GLM Coding Plan 套餐 key 在标准 OpenAI 端点上会报余额不足/空响应——"
                "套餐用户请选列表第一项 GLM Coding Plan"
            )

        quick = _model_pick(catalog_provider, "quick", st.session_state.get(
            "sb_quick_model", DEFAULT_CONFIG["quick_think_llm"]))
        deep = _model_pick(catalog_provider, "deep", st.session_state.get(
            "sb_deep_model", DEFAULT_CONFIG["deep_think_llm"]))
        backend = st.text_input(
            "API 端点（backend_url）",
            value=st.session_state.get(
                "sb_backend",
                default_backend or DEFAULT_CONFIG.get("backend_url") or "",
            ),
            key="sb_backend",
            help="留空用该提供商默认端点；.env 里的 TRADINGAGENTS_LLM_BACKEND_URL 是持久配置",
        )
        st.session_state["sb_quick_model"] = quick
        st.session_state["sb_deep_model"] = deep

        if engine_provider != DEFAULT_CONFIG["llm_provider"] or quick != DEFAULT_CONFIG["quick_think_llm"]:
            st.caption("⚠️ 以上为本次会话的覆盖值；持久配置请写入 .env（TRADINGAGENTS_*）")

    # -- API key 状态 ----------------------------------------------------------
    with st.sidebar.expander("🔑 API Key 状态", expanded=False):
        status = check_api_keys(engine_provider)
        st.markdown(get_api_key_status_message(engine_provider))
        for var, info in status["details"].items():
            mark = "✅" if info["configured"] else "❌"
            req = "必填" if info["required"] else "可选"
            st.caption(f"{mark} `{var}`（{req}）{info['description']}")

    # -- 输出语言 ----------------------------------------------------------------
    with st.sidebar.expander("🌐 输出语言", expanded=False):
        _LANGS = {"English": "English", "Chinese": "中文 (Chinese)", "Japanese": "日本語",
                  "Korean": "한국어", "custom": "自定义…"}
        current_lang = st.session_state.get("sb_language", DEFAULT_CONFIG["output_language"])
        if current_lang not in _LANGS:  # an env-configured custom language
            _LANGS[current_lang] = current_lang
        lang_pick = st.selectbox(
            "报告输出语言",
            options=list(_LANGS),
            index=list(_LANGS).index(current_lang),
            format_func=lambda v: _LANGS[v],
            key="sb_language_pick",
            help="影响所有分析师报告与最终决策的语言；.env 里 TRADINGAGENTS_OUTPUT_LANGUAGE 是持久配置",
        )
        if lang_pick == "custom":
            output_language = st.text_input(
                "语言名称（如 Turkish、Vietnamese）",
                value=current_lang if current_lang != "English" else "",
                key="sb_language_custom",
            ) or "English"
        else:
            output_language = lang_pick
        st.session_state["sb_language"] = output_language

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
        "llm_provider": engine_provider,
        "llm_model": quick,
        "deep_model": deep,
        "backend_url": backend or default_backend,
        "output_language": output_language,
    }
