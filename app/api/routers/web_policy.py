"""Web access policy & search configuration API (Sprint 13, §17.3).

Endpoints:
    GET  /api/web-policy         — get current policy + search config
    PUT  /api/web-policy         — update policy + search config
    GET  /api/web-policy/providers — list available search providers
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import require_gateway_token
from app.tools.builtin.web_search import (
    SearchConfig,
    get_search_config,
    get_search_registry,
    set_search_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/web-policy",
    tags=["web-policy"],
    dependencies=[Depends(require_gateway_token)],
)


# ── Models ─────────────────────────────────────────────────────────────────────


class WebPolicy(BaseModel):
    """Combined web access policy configuration."""

    # Search
    default_provider: str = "duckduckgo"
    max_results: int = 10
    safe_search: str = "moderate"
    timeout_s: int = 15

    # Provider API keys (write-only; empty string means unchanged)
    brave_api_key: str = ""
    tavily_api_key: str = ""
    google_api_key: str = ""
    google_cx: str = ""
    bing_api_key: str = ""
    searxng_url: str = ""

    # URL access controls
    url_blocklist: list[str] = []
    url_allowlist: list[str] = []
    blocklist_mode: str = "blocklist"  # "blocklist" | "allowlist"

    # Rate limiting
    requests_per_minute: int = 0  # 0 = unlimited


# In-memory storage for URL policy (persisted via config_store in a real app).
_url_policy: dict[str, Any] = {
    "url_blocklist": [],
    "url_allowlist": [],
    "blocklist_mode": "blocklist",
    "requests_per_minute": 0,
}


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=WebPolicy)
async def get_web_policy() -> WebPolicy:
    """Get current web access policy and search configuration."""
    cfg = get_search_config()
    return WebPolicy(
        default_provider=cfg.default_provider,
        max_results=cfg.max_results,
        safe_search=cfg.safe_search,
        timeout_s=cfg.timeout_s,
        searxng_url=cfg.searxng_url,
        **_url_policy,
    )


@router.put("", response_model=WebPolicy)
async def update_web_policy(policy: WebPolicy) -> WebPolicy:
    """Update web access policy and search provider configuration."""
    global _url_policy  # noqa: PLW0603
    cfg = get_search_config()

    # Build updated SearchConfig; preserve existing keys if new value is empty.
    new_cfg = SearchConfig(
        default_provider=policy.default_provider,
        max_results=policy.max_results,
        safe_search=policy.safe_search,
        timeout_s=policy.timeout_s,
        brave_api_key=policy.brave_api_key or cfg.brave_api_key,
        tavily_api_key=policy.tavily_api_key or cfg.tavily_api_key,
        google_api_key=policy.google_api_key or cfg.google_api_key,
        google_cx=policy.google_cx or cfg.google_cx,
        bing_api_key=policy.bing_api_key or cfg.bing_api_key,
        searxng_url=policy.searxng_url or cfg.searxng_url,
    )
    set_search_config(new_cfg)

    _url_policy = {
        "url_blocklist": policy.url_blocklist,
        "url_allowlist": policy.url_allowlist,
        "blocklist_mode": policy.blocklist_mode,
        "requests_per_minute": policy.requests_per_minute,
    }
    logger.info("Web policy updated: provider=%r", new_cfg.default_provider)
    return await get_web_policy()


@router.get("/providers")
async def list_providers() -> dict[str, Any]:
    """List all available search providers."""
    registry = get_search_registry()
    cfg = get_search_config()
    providers = []
    for name in registry.names():
        needs_key = name not in ("duckduckgo", "searxng")
        is_configured = True
        if name == "brave":
            is_configured = bool(cfg.brave_api_key)
        elif name == "tavily":
            is_configured = bool(cfg.tavily_api_key)
        elif name == "google":
            is_configured = bool(cfg.google_api_key and cfg.google_cx)
        elif name == "bing":
            is_configured = bool(cfg.bing_api_key)
        elif name == "searxng":
            is_configured = bool(cfg.searxng_url)
        providers.append({
            "name": name,
            "needs_api_key": needs_key,
            "is_configured": is_configured,
            "is_default": name == cfg.default_provider,
        })
    return {"providers": providers}
