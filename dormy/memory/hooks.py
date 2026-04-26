"""Fire-and-forget extractor hooks for MCP tool calls.

Each tool calls `from_mcp_call(tool_name, input, output)` at the end of its
handler. Inside, we:
  1. Resolve current user_id (BYOK ContextVar or DORMY_USER_ID fallback).
  2. Build 2 ConversationMessage equivalents from input + output.
  3. Schedule extractor.run_batch on the running event loop as a task.
  4. Return immediately — caller never awaits.

Safety:
  - No-ops cleanly if user_id can't be resolved (logs at debug).
  - No-ops cleanly if there's no running event loop (logs at debug).
  - run_batch already swallows all errors — never propagates.

This is "good enough" Wave 3: every successful MCP tool call eventually
produces a Sonnet 4.6 batch. Future improvements:
  - Batch multiple tool calls within a session window before triggering
  - Skip if recent batch < threshold (use observations.latest_batch_time)
  - Per-tool sampling (e.g. only every 5th profile_set)
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from loguru import logger

from dormy.auth import get_current_user_id
from dormy.memory.extractor import (
    ConversationMessage,
    ExtractionInput,
    run_batch,
)


def from_mcp_call(
    tool_name: str,
    tool_input: dict[str, Any] | None = None,
    tool_output: Any = None,
) -> None:
    """Trigger a fire-and-forget extractor batch from one MCP tool call.

    Synchronous return; the actual work runs as an asyncio task scheduled
    on the currently running event loop (FastMCP's loop in stdio/http modes).

    Side effects: writes to user_observations, calls Sonnet 4.6 + embeddings.
    Both already log + swallow their own errors — failures here never
    propagate to the user-facing tool response.
    """
    user_id = get_current_user_id()
    if user_id is None:
        logger.debug(
            f"hooks.from_mcp_call({tool_name}): no user_id, skipping"
        )
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug(
            f"hooks.from_mcp_call({tool_name}): no running loop, skipping"
        )
        return

    call_id = uuid.uuid4().hex[:8]
    timestamp = str(int(time.time()))

    input_str = (
        json.dumps(tool_input, ensure_ascii=False)[:1000]
        if tool_input
        else "(no input)"
    )
    output_str = _stringify(tool_output)[:1000]

    messages = [
        ConversationMessage(
            id=f"{tool_name}:input:{call_id}",
            role="user",
            content=f"[MCP tool: {tool_name}] input: {input_str}",
            timestamp=timestamp,
        ),
        ConversationMessage(
            id=f"{tool_name}:output:{call_id}",
            role="assistant",
            content=f"[MCP tool: {tool_name}] output: {output_str}",
            timestamp=timestamp,
        ),
    ]

    ei = ExtractionInput(
        user_id=user_id,
        source="mcp",
        session_id=tool_name,  # group observations by tool name
        messages=messages,
    )

    loop.create_task(_run_with_log(ei))


async def _run_with_log(ei: ExtractionInput) -> None:
    """Wrapper that logs success/failure of the background batch."""
    try:
        result = await run_batch(ei)
        if result.error:
            logger.warning(
                f"hook batch {result.batch_id} (user={ei.user_id}, "
                f"tool={ei.session_id}) completed with error: {result.error}"
            )
        else:
            logger.info(
                f"hook batch {result.batch_id} (user={ei.user_id}, "
                f"tool={ei.session_id}): {len(result.new_observations)} obs"
            )
    except Exception as e:
        logger.error(
            f"hook batch failed (user={ei.user_id}, tool={ei.session_id}): {e}"
        )


def _stringify(value: Any) -> str:
    """Best-effort string conversion of tool output for the prompt."""
    if value is None:
        return "(no output)"
    if isinstance(value, str):
        return value
    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump()
        except Exception:
            pass
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return repr(value)
