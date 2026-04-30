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
import re
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from uuid import UUID, uuid4

from loguru import logger
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReactionTypeEmoji,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from dormy.config import settings
from dormy.knowledge.retrieve import recall as knowledge_recall
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
from dormy.telegram.tools import TOOL_SCHEMAS, execute_tool

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

SYSTEM_PROMPT = """You are Dormy, the AI copilot for super founders. Two domains, equal weight:

- **Fundraising**: investors, intros, pitch positioning, deal timing.
- **GTM**: ICP & positioning, copy & cold outreach, landing-page CRO, SEO/AI-SEO, pricing & launches.

You have access to a curated 40-skill GTM playbook library (Cold Email, Page CRO, Customer Research, Pricing, Launch, etc. — adapted from coreyhaines31/marketingskills). When the founder's question maps to a playbook, ground your answer in that framework. Don't dump the playbook; apply it. Cite the playbook by name when you use one (e.g. "[Cold Email playbook]").

Voice rules:
- Direct, useful, dry. No hedging, no preamble, no "great question".
- Mirror the founder's language (English / Chinese — match what they wrote).
- One concrete next step beats three abstract options.
- If you don't know, say so and ask the one specific question that would unblock you.

You have these live tools — use them when the question calls for current data:

- web_search(query, n=5): real-time Tavily search. Use when the user asks about a specific company / website / person they referenced (e.g. "what does sekureclaw.ai do?") or wants fresh news / signals. Don't claim you can't access the web — you can.

- recent_funding(sector?, stage?, days=30): curated funding-rounds database (TechCrunch + 36kr + Pandaily + startups.gallery, refreshed daily). Use when user wants real funding data — "who just raised in AI infra", "AI infra deals last 30 days" — instead of your training-data guesses.

- list_skills(category?) + run_skill(name, input): the 42-skill GTM + fundraising playbook library (cold-email, page-cro, customer-research, pricing-strategy, launch-strategy, etc.). Categories: copy, cro, seo, distribution, growth, strategy, foundations, icp, fundraising.

CRITICAL skill workflow — the playbooks are Dormy's IP, you MUST execute them, not paraphrase:
1. When the user asks for a concrete deliverable (cold email, landing-page critique, ICP analysis, pricing memo, launch plan, ad copy, SEO audit, etc.), this maps to a skill — go straight to run_skill if you know the slug, OR call list_skills(category=...) first to find it.
2. list_skills returns ONLY names + trigger-descriptions. It does NOT contain the framework. You MUST follow up with run_skill(name, input) to actually load and apply the playbook. Never synthesize a deliverable from a list_skills response alone.
3. Common slugs you can call directly: gtm-cold-email, gtm-page-cro, gtm-customer-research, gtm-pricing-strategy, gtm-launch-strategy, gtm-copywriting, gtm-ad-creative, gtm-seo-audit, gtm-email-sequence, gtm-onboarding-cro.
4. For run_skill, pass a FULL paragraph of context as `input`: their situation + product + target + constraints + voice notes. Quality of input drives quality of output.

Tool budget: up to 4 rounds per turn. Use them. A typical deliverable turn = 1 round (run_skill directly) or 2 rounds (list_skills → run_skill). For research-heavy answers, you can also chain web_search → run_skill. Only stop tool-calling once you have enough to write a real answer in the founder's voice — don't stop early just to be safe.

Default to using a tool when the question is about specific companies, recent events, or anything time-sensitive — or when the user wants a structured deliverable (the skill library). After a tool returns, synthesize the result into a useful answer in the founder's language; don't just dump JSON.

For everything else (quick coaching, decision frames, off-cuff drafts where no skill obviously applies), keep doing what you do — concrete answers in the founder's voice."""

# Lightweight router. Output structure must match exactly so the regex
# parser in `_classify_topic` can extract values without a JSON parser.
# Categories mirror the marketingskills sub-tags in the GTM RAG.
ROUTER_MODEL = CHAT_MODEL  # same model — Haiku is cheap enough at ~$0.0001/turn
ROUTER_PROMPT = """Classify the user's message for routing. Output EXACTLY 3 lines, no preamble:

DOMAIN: one of [fundraising, gtm, both, neither]
GTM_CATEGORY: if domain includes gtm, one of [icp, copy, cro, seo, distribution, growth, strategy, foundations]; else "none"
SKILL: if there's a clear single playbook to suggest as a workflow, output its slug (e.g. "cold-email", "page-cro", "customer-research"); else "none"

User message:
{message}"""

# Map skill slugs to display names (for inline button + system-prompt grounding)
SKILL_LABELS = {
    "customer-research": "Customer Research",
    "competitor-profiling": "Competitor Profiling",
    "competitor-alternatives": "Competitor Alternatives",
    "product-marketing-context": "Product Marketing Context",
    "copywriting": "Copywriting",
    "copy-editing": "Copy Editing",
    "cold-email": "Cold Email",
    "email-sequence": "Email Sequence",
    "ad-creative": "Ad Creative",
    "page-cro": "Page CRO",
    "form-cro": "Form CRO",
    "popup-cro": "Popup CRO",
    "onboarding-cro": "Onboarding CRO",
    "signup-flow-cro": "Signup Flow CRO",
    "paywall-upgrade-cro": "Paywall Upgrade CRO",
    "seo-audit": "SEO Audit",
    "ai-seo": "AI SEO",
    "programmatic-seo": "Programmatic SEO",
    "schema-markup": "Schema Markup",
    "site-architecture": "Site Architecture",
    "paid-ads": "Paid Ads",
    "social-content": "Social Content",
    "video": "Video",
    "image": "Image",
    "community-marketing": "Community Marketing",
    "directory-submissions": "Directory Submissions",
    "lead-magnets": "Lead Magnets",
    "referral-program": "Referral Program",
    "free-tool-strategy": "Free Tool Strategy",
    "churn-prevention": "Churn Prevention",
    "aso-audit": "ASO Audit",
    "pricing-strategy": "Pricing Strategy",
    "launch-strategy": "Launch Strategy",
    "content-strategy": "Content Strategy",
    "marketing-ideas": "Marketing Ideas",
    "analytics-tracking": "Analytics Tracking",
    "ab-test-setup": "A/B Test Setup",
    "marketing-psychology": "Marketing Psychology",
    "sales-enablement": "Sales Enablement",
    "revops": "RevOps",
}

# Active skill workflow state — keyed by chat_id, value = (skill_slug, ts_unix).
# Set on inline-button click; consumed on the user's NEXT message; auto-expires
# after ACTIVE_SKILL_TTL seconds (in case user changes topic without /reset).
_active_skill: dict[int, tuple[str, float]] = {}
ACTIVE_SKILL_TTL = 300.0  # 5 min

# Cache for full skill content (read from disk on first use, stays in memory)
_SOURCES_DIR = (
    Path(__file__).resolve().parents[2]
    / "dormy-skills"
    / "sources"
    / "marketingskills"
    / "skills"
)
_skill_text_cache: dict[str, str] = {}


def _load_skill_full_text(slug: str) -> str:
    """Read the full SKILL.md body for `slug` from the vendored sources.

    Returns "" if not found — caller can fall back to RAG excerpts."""
    if slug in _skill_text_cache:
        return _skill_text_cache[slug]
    skill_md = _SOURCES_DIR / slug / "SKILL.md"
    if not skill_md.is_file():
        _skill_text_cache[slug] = ""
        return ""
    try:
        text = skill_md.read_text()
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                text = parts[2].lstrip("\n")
        _skill_text_cache[slug] = text
        return text
    except Exception as e:  # noqa: BLE001
        logger.warning(f"failed to read skill {slug}: {e}")
        _skill_text_cache[slug] = ""
        return ""


_ROUTER_LINE_RE = re.compile(r"^(DOMAIN|GTM_CATEGORY|SKILL):\s*(.+)$", re.MULTILINE)


async def _classify_topic(message: str) -> dict[str, str]:
    """Run the router LLM. Returns {'domain', 'gtm_category', 'skill'}.

    Defaults to neither/none on parse failure — bot just replies normally."""
    try:
        client = get_openrouter_client()
        resp = await client.chat.completions.create(
            model=ROUTER_MODEL,
            messages=[
                {"role": "user", "content": ROUTER_PROMPT.format(message=message)}
            ],
            max_tokens=80,
            temperature=0.0,
        )
        output = (resp.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"router classifier failed: {e}")
        return {"domain": "neither", "gtm_category": "none", "skill": "none"}

    parsed: dict[str, str] = {
        "domain": "neither",
        "gtm_category": "none",
        "skill": "none",
    }
    for m in _ROUTER_LINE_RE.finditer(output):
        key = m.group(1).lower()
        val = m.group(2).strip().strip("[]\"'").lower()
        if key == "gtm_category":
            parsed["gtm_category"] = val
        elif key == "skill":
            parsed["skill"] = val
        elif key == "domain":
            parsed["domain"] = val
    return parsed


async def _gtm_rag_context(query: str, sub_tag: str, limit: int = 4) -> str:
    """Pull GTM playbook excerpts for system-prompt injection. Returns "" on
    miss or error so callers can simply concatenate."""
    if sub_tag in {"none", ""}:
        return ""
    try:
        hits, _mode = await knowledge_recall(
            query=query,
            tags=["gtm", sub_tag],
            limit=limit,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"gtm RAG recall failed: {e}")
        return ""
    if not hits:
        return ""
    blocks = []
    for h in hits:
        label = h.title or "playbook"
        blocks.append(f"### {label}\n{h.excerpt}")
    return (
        "\n\n## Relevant GTM playbook excerpts (apply, don't dump)\n\n"
        + "\n\n".join(blocks)
    )


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


# Cap tool-call rounds in a single turn. After a few rounds the model is
# usually looping uselessly; better to bail than burn tokens.
MAX_TOOL_ROUNDS = 4

# Per tool result we send back to the model — cap the JSON we serialize
# so a giant Tavily response doesn't blow context.
TOOL_RESULT_CAP_CHARS = 6000


async def _llm_reply(
    chat_id: int,
    user_text: str,
    message_id: str,
    extra_system: str = "",
) -> str:
    """Call OpenRouter with system prompt + transcript, with tool-calling.

    Loop:
      1. Send messages + tool schemas to the model.
      2. If the model returns a final assistant message, persist + return it.
      3. If the model returns tool_calls, execute each one against
         `dormy.telegram.tools.execute_tool`, append the assistant
         tool-call message + each tool result, loop back to (1).
      4. Bound at MAX_TOOL_ROUNDS rounds; emit a graceful fallback
         if the model still wants to call tools after that.
    """
    history = _history[chat_id]
    history.append(("user", user_text, message_id))

    system_full = SYSTEM_PROMPT + extra_system
    messages: list[dict] = [{"role": "system", "content": system_full}]
    for role, content, _ in history:
        messages.append({"role": role, "content": content})

    client = get_openrouter_client()
    reply: str = ""

    for round_idx in range(MAX_TOOL_ROUNDS):
        resp = await client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,  # type: ignore[arg-type]
            tools=TOOL_SCHEMAS,  # type: ignore[arg-type]
            tool_choice="auto",
            max_tokens=CHAT_MAX_TOKENS,
            temperature=CHAT_TEMPERATURE,
        )
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []

        if not tool_calls:
            reply = (msg.content or "").strip()
            break

        # Append the assistant message with tool_calls (required by the spec
        # so the model can match its own tool_call_ids on the next turn).
        assistant_msg = {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        }
        messages.append(assistant_msg)

        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            logger.info(
                f"telegram tool call: {tc.function.name} args={args} round={round_idx}"
            )
            result = await execute_tool(tc.function.name, args)
            content = json.dumps(result, ensure_ascii=False)[:TOOL_RESULT_CAP_CHARS]
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": content,
                }
            )

    if not reply:
        # Loop exhausted — model kept asking for tools. Fall back gracefully.
        reply = (
            "我查得有点久,你换个角度再问问看,或者把问题拆细一点。"
            if any("\u4e00" <= c <= "\u9fff" for c in user_text)
            else "I went a bit deep on that. Mind asking a tighter version?"
        )

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


async def _typing_pulse(bot, chat_id: int, stop: asyncio.Event) -> None:
    """Re-send 'typing' chat action every 4s until stop is set.

    Telegram's typing indicator auto-expires after ~5s, so for long-running
    LLM calls we need to keep nudging it. Stops cleanly when the caller
    sets `stop` (in finally block)."""
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"typing pulse send_chat_action failed: {e}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=4.0)
        except asyncio.TimeoutError:
            continue


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

    # 👀 emoji reaction on the user's message — instant "I see you" feedback
    # even if the LLM call takes a few seconds. Continuous typing pulse below
    # keeps the "is typing…" indicator alive for the duration of generation.
    try:
        await context.bot.set_message_reaction(
            chat_id=chat_id,
            message_id=msg.message_id,
            reaction=[ReactionTypeEmoji(emoji="👀")],
        )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"set_message_reaction failed (non-fatal): {e}")

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        _typing_pulse(context.bot, chat_id, stop_typing)
    )

    # Bind user_id to this turn so any downstream code (extractor, future
    # MCP tool calls) can attribute writes.
    token = current_user_id.set(user.id)
    try:
        message_id = f"tg-{msg.message_id}-{uuid4().hex[:6]}"

        # If user is mid-skill workflow (clicked an inline button recently),
        # inject the full skill markdown as extra system context. One-shot:
        # consume the active state after this turn so subsequent unrelated
        # messages don't keep dragging the framework along.
        active_skill_text = ""
        suggested_skill: str | None = None
        active = _active_skill.get(chat_id)
        if active and (time.time() - active[1]) <= ACTIVE_SKILL_TTL:
            slug = active[0]
            full = _load_skill_full_text(slug)
            if full:
                active_skill_text = (
                    f"\n\n## Active workflow: {SKILL_LABELS.get(slug, slug)}\n\n"
                    "The user has explicitly invoked this playbook. Apply its\n"
                    "framework end-to-end on whatever they wrote next. After\n"
                    "delivering output, ask if they want a follow-up draft or\n"
                    "to switch topics.\n\n"
                    f"### Playbook source ({slug})\n\n{full}"
                )
                _active_skill.pop(chat_id, None)  # consume

        # Otherwise, route the message to inject lighter RAG context (if GTM)
        # and decide whether to suggest a deeper workflow via inline button.
        rag_text = ""
        if not active_skill_text:
            classification = await _classify_topic(msg.text)
            sub = classification["gtm_category"]
            if sub != "none":
                rag_text = await _gtm_rag_context(msg.text, sub)
            skill_slug = classification["skill"]
            if skill_slug != "none" and skill_slug in SKILL_LABELS:
                suggested_skill = skill_slug

        try:
            reply = await _llm_reply(
                chat_id,
                msg.text,
                message_id,
                extra_system=active_skill_text or rag_text,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"telegram-bot LLM call failed for user {user.id}: {e}")
            await msg.reply_text(
                "Hmm, I hit an error reaching my brain. Try again in a moment?"
            )
            return

        # Send reply, optionally with an inline button for deeper workflow.
        reply_kwargs: dict = {}
        if suggested_skill:
            label = SKILL_LABELS[suggested_skill]
            reply_kwargs["reply_markup"] = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            text=f"📋 Apply [{label}] playbook",
                            callback_data=f"skill:{suggested_skill}",
                        )
                    ]
                ]
            )
        await msg.reply_text(reply, **reply_kwargs)
        _maybe_fire_extractor(user.id, chat_id)
    finally:
        stop_typing.set()
        try:
            await asyncio.wait_for(typing_task, timeout=2.0)
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001
            typing_task.cancel()
        current_user_id.reset(token)


async def _skill_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle inline button taps with `callback_data='skill:<slug>'`.

    Sets the chat's active_skill state so the user's NEXT text message
    triggers a full-playbook reply. Acks the callback (Telegram requires)
    and sends a brief confirmation prompt asking for the inputs the
    skill needs."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()  # required by Telegram, dismisses loading spinner

    if not query.data.startswith("skill:"):
        return
    slug = query.data.split(":", 1)[1]
    if slug not in SKILL_LABELS:
        return
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = chat.id

    # Verify user is bound (re-checks gate even though they got this far)
    user = await user_by_telegram_chat_id(chat_id)
    if user is None:
        return

    _active_skill[chat_id] = (slug, time.time())
    label = SKILL_LABELS[slug]
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"OK — applying the [{label}] playbook to your next message.\n\n"
            "Tell me what you're working with (the recipient / the page / "
            "the audience / the angle — whatever specifics fit). I'll draft "
            "or review using the framework end-to-end.\n\n"
            "_(One-shot — your next reply triggers the full workflow. "
            "Type /reset to cancel.)_"
        ),
        parse_mode="Markdown",
    )


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
    app.add_handler(CallbackQueryHandler(_skill_callback_handler, pattern=r"^skill:"))
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
