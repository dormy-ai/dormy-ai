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
from dormy.telemetry import log_tool_call


def from_mcp_call(
    tool_name: str,
    tool_input: dict[str, Any] | None = None,
    tool_output: Any = None,
) -> None:
    """Trigger fire-and-forget side effects for one MCP tool call:
      1. Telemetry: log the call into tool_call_log (status from output's
         data_source field if present).
      2. Memory extractor: kick off a Sonnet batch to extract observations.

    Synchronous return; both side effects run as asyncio tasks scheduled
    on the currently running event loop (FastMCP's loop in stdio/http modes).
    Both already log + swallow their own errors — failures here never
    propagate to the user-facing tool response.
    """
    # 1. Telemetry — runs even when no user_id (still useful for catching
    #    tool error bursts from the MCP surface in dev).
    status = "ok"
    error_msg: str | None = None
    if hasattr(tool_output, "model_dump"):
        try:
            dumped = tool_output.model_dump()
        except Exception:  # noqa: BLE001
            dumped = {}
        if isinstance(dumped, dict) and dumped.get("data_source") == "error":
            status = "error"
            error_msg = str(dumped.get("note") or "tool returned data_source=error")
    log_tool_call(
        source="mcp",
        tool_name=tool_name,
        status=status,
        latency_ms=0,  # MCP wrappers don't time themselves; 0 = unknown
        error_msg=error_msg,
        args=tool_input,
        user_id=get_current_user_id(),
    )

    # 2. Memory extractor — needs a user_id, otherwise can't attribute.
    user_id = get_current_user_id()
    if user_id is None:
        logger.debug(
            f"hooks.from_mcp_call({tool_name}): no user_id, skipping extractor"
        )
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug(
            f"hooks.from_mcp_call({tool_name}): no running loop, skipping extractor"
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
