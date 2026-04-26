"""BYOK middleware — parses `Authorization: Bearer <key>` from incoming
HTTP requests and exposes the user's key via a ContextVar.

LLM call sites read the key via `dormy.llm.client.get_openrouter_client()`.
When called from CLI batch jobs (no middleware in scope) the ContextVar is
None and the helper falls back to `settings.openrouter_api_key`.

Why a ContextVar (not request state):
- FastMCP's tool functions don't receive the HTTP request object; they're
  invoked via the MCP JSON-RPC dispatch. The only way to thread per-request
  state through is via contextvars (Python's task-local storage).
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

# Set per-request by BYOKMiddleware below. None = no header (stdio mode or
# unauthenticated HTTP). LLM call sites fall back to settings when None.
current_user_key: ContextVar[str | None] = ContextVar(
    "current_user_key", default=None
)


class BYOKMiddleware:
    """ASGI middleware. Reads `Authorization: Bearer <key>` from incoming
    HTTP requests and stuffs the bare key into `current_user_key` for the
    duration of the request, then resets it.

    Does not validate the key. Does not 401 if missing. v1 design is "graceful
    BYOK" — current MCP tools mostly return mock data and do not require an
    LLM key, so we don't want to block requests on missing headers. When
    expensive tools land (Week 4: Sonnet drafting in intro_writer), the LLM
    call sites themselves enforce key presence via `get_openrouter_client()`.
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

        reset_to = current_user_key.set(token)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user_key.reset(reset_to)
