"""Live model list from Zhipu's official API.

The GLM Coding Plan key authenticates against the Anthropic-compatible
endpoint, which serves the standard Anthropic ``GET /v1/models`` listing.
Fetched here (cached an hour) so the sidebar never shows a stale catalog;
on any failure callers fall back to the static model_catalog.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_ZHIPU_MODELS_URLS = (
    "https://api.z.ai/api/anthropic/v1/models?limit=100",
    "https://open.bigmodel.cn/api/anthropic/v1/models?limit=100",
)


def _api_key() -> str | None:
    # Load .env ourselves when imported outside the engine's package init
    # (which already ran load_dotenv) — idempotent either way.
    try:
        from dotenv import find_dotenv, load_dotenv

        load_dotenv(find_dotenv(usecwd=True))
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ZHIPU_API_KEY")


def _fetch_models_uncached() -> list[dict]:
    """Newest-first model entries (``id`` + ``display_name``); empty on failure."""
    key = _api_key()
    if not key:
        return []
    import requests

    for url in _ZHIPU_MODELS_URLS:
        try:
            r = requests.get(
                url,
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json().get("data") or []
            models = [m for m in data if m.get("id")]
            models.sort(key=lambda m: m.get("created_at") or "", reverse=True)
            if models:
                return models
        except Exception as exc:
            logger.debug("zhipu model list fetch failed (%s): %s", url, exc)
    return []


def fetch_zhipu_models() -> list[dict]:
    """Streamlit-cached wrapper; safe outside a streamlit runtime."""
    try:
        import streamlit as st

        return st.cache_data(ttl=3600, show_spinner=False)(_fetch_models_uncached)()
    except Exception:
        return _fetch_models_uncached()
