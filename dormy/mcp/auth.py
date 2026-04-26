"""BYOK middleware — parses `Authorization: Bearer <key>` from incoming
HTTP requests and exposes the user's key + resolved user_id via ContextVars.

LLM call sites read the key via `dormy.llm.client.get_openrouter_client()`.
User-attribution call sites (e.g. user_observations) read the user_id via
`dormy.auth.get_current_user_id()`.

When called from CLI batch jobs (no middleware in scope) the ContextVars are
None and helpers fall back to settings.openrouter_api_key / settings.user_id.

Why ContextVars (not request state):
- FastMCP's tool functions don't receive the HTTP request object; they're
  invoked via the MCP JSON-RPC dispatch. The only way to thread per-request
  state through is via contextvars (Python's task-local storage).
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any
from uuid import UUID

from loguru import logger

# Set per-request by BYOKMiddleware below. None = no header (stdio mode or
# unauthenticated HTTP). LLM call sites fall back to settings when None.
current_user_key: ContextVar[str | None] = ContextVar(
    "current_user_key", default=None
)

# Set per-request by BYOKMiddleware after resolve_or_create_user succeeds.
# None = no key OR resolution failed. user_observations attribution falls
# back to settings.user_id when None (see dormy.auth.get_current_user_id).
current_user_id: ContextVar[UUID | None] = ContextVar(
    "current_user_id", default=None
)


class BYOKMiddleware:
    """ASGI middleware. Reads `Authorization: Bearer <key>` from incoming
    HTTP requests, lazy-resolves the user_id, and stuffs both into ContextVars
    for the duration of the request, then resets them.

    Does not validate the key. Does not 401 if missing. v1 design is "graceful
    BYOK" — current MCP tools mostly return mock data and do not require an
    LLM key, so we don't want to block requests on missing headers. When
    expensive tools land (Week 4: Sonnet drafting in intro_writer), the LLM
    call sites themselves enforce key presence via `get_openrouter_client()`.

    User_id resolution is best-effort: if resolve_or_create_user raises
    (DB down, race we couldn't recover from, etc.) the request still proceeds
    with current_user_id=None — observations fall back to settings.user_id.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token: str | None = None
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                v = value.decode("latin-1")
                if v.startswith("Bearer "):
                    token = v[len("Bearer ") :].strip() or None
                break

        key_token = current_user_key.set(token)
        id_token = current_user_id.set(None)
        try:
            if token:
                # Lazy import to avoid circular: dormy.auth imports from us.
                from dormy.auth import resolve_or_create_user

                try:
                    uid = await resolve_or_create_user(token)
                    current_user_id.set(uid)
                except Exception as e:
                    logger.error(
                        f"BYOK: failed to resolve user_id for key "
                        f"{token[:12]}… — proceeding with None: {e}"
                    )
            await self.app(scope, receive, send)
        finally:
            current_user_key.reset(key_token)
            current_user_id.reset(id_token)
