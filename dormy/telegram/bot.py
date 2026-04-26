"""Dormy Telegram bot — gated by invite tokens, hosted by Dormy.

Lifecycle:
1. User clicks `t.me/dormy_dev01_bot?start=<token>`. Telegram opens a
   chat and posts `/start <token>` to us.
2. `/start` handler consumes the invite (binds chat_id ↔ user_id,
   marks token spent), greets the founder.
3. Subsequent messages from that chat resolve to the bound user via
   `users.telegram_chat_id`. We:
     - Set the `current_user_id` ContextVar so memory hooks attribute
       observations correctly.
     - Append to a per-chat in-memory transcript (last N turns).
     - Reply via OpenRouter (Dormy-paid, NOT BYOK — bot path is hosted).
     - Fire-and-forget extractor batches every N user turns to persist
       goals / preferences / facts into `user_observations`.

This is the v1 chat surface: no MCP tool calls yet, just a focused
fundraising copilot persona with persistent memory across sessions.
Tool integration (find_investors, draft_intro, etc.) lands in Phase 3.

Run via `dormy telegram-serve` after setting `DORMY_TELEGRAM_BOT_TOKEN`.
Long-polling — no public webhook required.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import UUID, uuid4

from loguru import logger
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from dormy.config import settings
from dormy.llm.client import get_openrouter_client
from dormy.mcp.auth import current_user_id
from dormy.memory.extractor import (
    ConversationMessage,
    ExtractionInput,
    run_batch,
)
from dormy.memory.observations import ObservationSource
from dormy.telegram.invites import (
    consume_invite,
    user_by_telegram_chat_id,
)

# In-memory transcript per chat. Keyed by chat_id, value is bounded deque
# of (role, content, message_id) tuples. Cleared on /reset, kept across
# messages but not across bot restarts. For multi-process scale, swap in
# redis/db. v1 single-process is fine.
HISTORY_LIMIT = 20  # ~10 user + 10 assistant turns
EXTRACT_EVERY_N_USER_TURNS = 5

_history: dict[int, deque[tuple[str, str, str]]] = defaultdict(
    lambda: deque(maxlen=HISTORY_LIMIT)
)
# Per-chat counter for triggering extractor batches
_user_turn_count: dict[int, int] = defaultdict(int)

CHAT_MODEL = "anthropic/claude-haiku-4-5"
CHAT_MAX_TOKENS = 1024
CHAT_TEMPERATURE = 0.7

SYSTEM_PROMPT = """You are Dormy, a fundraising copilot for founders. You're helping the founder think about their raise — investors, intros, pitch positioning, GTM, hiring, and timing.

Voice rules:
- Direct, useful, dry. No hedging, no preamble, no "great question".
- Mirror the founder's language (English / Chinese — match what they wrote).
- One concrete next step beats three abstract options.
- If you don't know, say so and ask the one specific question that would unblock you.

You don't have live tool access in this chat yet (find_investors, draft_intro, etc. are coming). For now, focus on coaching and prep — concrete drafts, decision frames, market intel from your training data."""


async def _start_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /start [token]. With token: consume invite. Without: gate message."""
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        return
    args = context.args or []

    # /start with no token (or already-bound user re-launching)
    if not args:
        existing = await user_by_telegram_chat_id(chat_id)
        if existing:
            await update.message.reply_text(
                f"Welcome back, {existing.email}. Ask me anything about your raise."
            )
            return
        await update.message.reply_text(
            "Hi — Dormy is currently invite-only.\n\n"
            "Request access at https://heydormy.ai/#get-in-touch and we'll send "
            "you a personalized invite link once approved."
        )
        return

    token = args[0]
    user = await consume_invite(token, telegram_chat_id=chat_id)
    if user is None:
        await update.message.reply_text(
            "That invite link is invalid or expired. "
            "Request a fresh one at https://heydormy.ai/#get-in-touch."
        )
        return

    # Reset transcript on fresh bind (covers re-invite case)
    _history.pop(chat_id, None)
    _user_turn_count.pop(chat_id, None)

    await update.message.reply_text(
        f"Welcome to Dormy, {user.email}.\n\n"
        "I'll remember our conversations across sessions — your goals, "
        "the investors you're targeting, your positioning. Ask me anything "
        "about fundraising and I'll keep building context over time.\n\n"
        "What are you working on?"
    )


async def _reset_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /reset — clear in-memory transcript (long-term memory persists)."""
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        return
    _history.pop(chat_id, None)
    _user_turn_count.pop(chat_id, None)
    await update.message.reply_text(
        "Cleared this session's chat history. Long-term memory of you stays."
    )


async def _llm_reply(
    chat_id: int, user_text: str, message_id: str
) -> str:
    """Call OpenRouter with system prompt + recent transcript + this user message."""
    history = _history[chat_id]
    history.append(("user", user_text, message_id))

    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for role, content, _ in history:
        messages.append({"role": role, "content": content})

    client = get_openrouter_client()
    resp = await client.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,  # type: ignore[arg-type]
        max_tokens=CHAT_MAX_TOKENS,
        temperature=CHAT_TEMPERATURE,
    )
    reply = (resp.choices[0].message.content or "").strip()
    history.append(("assistant", reply, f"a-{message_id}"))
    return reply


def _maybe_fire_extractor(user_id: UUID, chat_id: int) -> None:
    """If user crossed the per-chat extraction threshold, schedule a batch.

    Fire-and-forget on the running event loop. No-op if loop is not running
    (shouldn't happen in bot context, but defensive)."""
    _user_turn_count[chat_id] += 1
    if _user_turn_count[chat_id] < EXTRACT_EVERY_N_USER_TURNS:
        return
    _user_turn_count[chat_id] = 0  # reset counter

    # Snapshot current history into ConversationMessages; the deque is mutable
    # so we copy now to avoid the running task observing later mutations.
    msgs = [
        ConversationMessage(
            id=mid,
            role=role,
            content=content,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        for role, content, mid in list(_history[chat_id])
    ]
    if not msgs:
        return
    extraction_input = ExtractionInput(
        user_id=user_id,
        source=ObservationSource("telegram"),
        session_id=str(chat_id),
        messages=msgs,
    )
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("telegram-bot: no running loop, skipping extractor")
        return
    loop.create_task(_run_extractor_safely(extraction_input))


async def _run_extractor_safely(extraction_input: ExtractionInput) -> None:
    try:
        await run_batch(extraction_input)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"telegram-bot extractor batch failed: {e}")


async def _message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle any non-command text message."""
    chat = update.effective_chat
    msg = update.message
    if chat is None or msg is None or not msg.text:
        return
    chat_id = chat.id

    user = await user_by_telegram_chat_id(chat_id)
    if user is None:
        await msg.reply_text(
            "I don't recognize you yet. Please use your invite link from "
            "heydormy.ai to get started, or request access at "
            "https://heydormy.ai/#get-in-touch."
        )
        return

    # Bind user_id to this turn so any downstream code (extractor, future
    # MCP tool calls) can attribute writes.
    token = current_user_id.set(user.id)
    try:
        # Show typing indicator while we generate
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        message_id = f"tg-{msg.message_id}-{uuid4().hex[:6]}"
        try:
            reply = await _llm_reply(chat_id, msg.text, message_id)
        except Exception as e:  # noqa: BLE001
            logger.error(f"telegram-bot LLM call failed for user {user.id}: {e}")
            await msg.reply_text(
                "Hmm, I hit an error reaching my brain. Try again in a moment?"
            )
            return
        await msg.reply_text(reply)
        _maybe_fire_extractor(user.id, chat_id)
    finally:
        current_user_id.reset(token)


def build_application() -> Application:
    """Construct the python-telegram-bot Application with handlers wired."""
    if not settings.telegram_bot_token:
        raise RuntimeError(
            "DORMY_TELEGRAM_BOT_TOKEN is not set. Get one from @BotFather."
        )
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )
    app.add_handler(CommandHandler("start", _start_handler))
    app.add_handler(CommandHandler("reset", _reset_handler))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _message_handler)
    )
    return app


class _HealthHandler(BaseHTTPRequestHandler):
    """Tiny /health endpoint so Railway's healthcheck passes for the bot service."""

    def do_GET(self) -> None:  # noqa: N802 — std lib API
        if self.path == "/health":
            payload = json.dumps({"ok": True, "service": "dormy-tg"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args, **kwargs) -> None:  # noqa: ARG002
        # Silence per-request access logging — Railway healthcheck runs every
        # ~10s and we don't need that noise in the bot logs.
        pass


def _start_health_server(port: int) -> None:
    """Spin up a daemon-thread HTTP server for /health on the Railway-injected PORT.

    Long-polling bot doesn't bind any port itself, so without this Railway's
    healthcheck (configured in railway.toml at /health) fails the deploy."""
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info(f"dormy-tg: health server listening on 0.0.0.0:{port}")


def serve() -> None:
    """Run the bot until Ctrl+C / SIGTERM."""
    # Railway injects PORT for HTTP services; we use it for the /health probe.
    port_env = os.environ.get("PORT")
    if port_env:
        try:
            _start_health_server(int(port_env))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"dormy-tg: failed to start health server: {e}")

    app = build_application()
    logger.info("dormy-tg: bot starting (long-polling)")
    app.run_polling(stop_signals=None)  # let our process supervisor handle signals
