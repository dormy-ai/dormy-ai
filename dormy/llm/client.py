"""Centralized OpenRouter client factory.

Reads the request-scoped user key set by `dormy.mcp.auth.BYOKMiddleware`
when serving over HTTP, with fallback to `settings.openrouter_api_key`
(used by CLI batch jobs and stdio-mode MCP local installs).

Embedding calls (`dormy.knowledge.embedder`) are intentionally NOT routed
through this helper — embeddings stay Dormy-hosted in v1 because:
  1. OpenRouter does not currently proxy `text-embedding-3-small`.
  2. Embedding cost per recall query is ~$0.00002 — negligible vs the
     per-Sonnet completion cost (~$0.03–0.10) that motivates BYOK.
"""

from __future__ import annotations

from openai import AsyncOpenAI

from dormy.config import settings
from dormy.mcp.auth import current_user_key

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def get_openrouter_client() -> AsyncOpenAI:
    """Return an AsyncOpenAI client pointed at OpenRouter.

    Resolution order for the API key:
      1. Request-scoped key from `current_user_key` ContextVar (BYOK).
      2. `settings.openrouter_api_key` (CLI batch / stdio fallback).

    Raises RuntimeError if neither is available.
    """
    raw_key = current_user_key.get() or settings.openrouter_api_key
    # Defensive strip — keys pasted into Railway / dashboard often pick up
    # trailing whitespace, which httpx rejects with "Illegal header value".
    key = raw_key.strip() if raw_key else None
    if not key:
        raise RuntimeError(
            "No OpenRouter API key available. Either pass "
            "`Authorization: Bearer <key>` on the MCP request, or set "
            "DORMY_OPENROUTER_API_KEY for CLI batch jobs / stdio-mode MCP."
        )
    return AsyncOpenAI(api_key=key, base_url=OPENROUTER_BASE_URL)
