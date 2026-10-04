"""API-key status for the surgo web UI.

Checks the env vars surgo's LLM clients actually read (single source of
truth: ``tradingagents.llm_clients.api_key_env``), plus the optional
data-vendor keys. Returns a status dict the sidebar renders.

Derived in shape from TradingAgents-CN's Apache-2.0-licensed
``web/utils/api_checker.py`` (provider list and validation rules replaced
with surgo's).
Copyright 2024-2026 hsliuping & TradingAgents-CN Contributors
Modifications for surgo: Copyright 2026 surgo contributors
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import os

from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV

# Optional data-vendor / enhancement keys; shown when present, never required.
_OPTIONAL_KEYS = {
    "FRED_API_KEY": "FRED 宏观数据（美股宏观指标）",
    "TUSHARE_TOKEN": "Tushare 行情（A 股降级链可选源）",
    "TYPESAFE_API_KEY": "TypeSafe 社交帖子过滤",
}


def check_api_keys(provider: str = "openai") -> dict:
    """Which keys the current provider needs, and which optional ones are set."""
    main_env = PROVIDER_API_KEY_ENV.get(provider)
    details: dict[str, dict] = {}
    if main_env:
        details[main_env] = {
            "configured": bool(os.environ.get(main_env)),
            "required": True,
            "description": f"{provider} 当前 LLM 提供商所需",
        }
    for var, desc in _OPTIONAL_KEYS.items():
        if os.environ.get(var):
            details[var] = {"configured": True, "required": False, "description": desc}
    required_ok = all(d["configured"] for d in details.values() if d["required"])
    return {
        "provider": provider,
        "required_env": main_env,
        "required_configured": required_ok,
        "details": details,
    }


def get_api_key_status_message(provider: str = "openai") -> str:
    status = check_api_keys(provider)
    if status["required_configured"]:
        extra = sum(1 for d in status["details"].values() if not d["required"])
        return f"✅ {status['required_env']} 已配置" + (f"，另有 {extra} 个可选数据源 key 已配置" if extra else "")
    if status["required_env"]:
        return f"❌ 未设置 {status['required_env']}——当前提供商无法调用"
    return "⚠️ 该提供商无需 API key（如 ollama）"
