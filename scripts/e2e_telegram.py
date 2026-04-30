"""End-to-end self-test for the Telegram bot's tool-calling loop.

Why this exists: production behavior depends on three layers — system prompt,
tool schemas, and how the LLM decides to chain them. Unit tests verify the
first two; only a live LLM call verifies the third. Before this script,
every "did the bot really call run_skill?" question forced the user to
re-test in Telegram. Now I run it, paste the transcript, and the user
just sees results.

Mirrors `dormy.telegram.bot._llm_reply` (chat completion loop with tool
dispatch) using the exact same constants, system prompt, schemas, and
executors. Only difference: in-memory history, no Telegram I/O.

Run:
    cd dormy-ai
    uv run python scripts/e2e_telegram.py

Requires `DORMY_OPENROUTER_API_KEY` in `.env`. Cost ~$0.05 / full run.
Exit 0 on all-green, 1 on any failure.

Output is plain text (no colors / spinners) so it can be pasted into
PR descriptions verbatim.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from dormy.llm.client import get_openrouter_client
from dormy.telegram.bot import (
    CHAT_MAX_TOKENS,
    CHAT_MODEL,
    CHAT_TEMPERATURE,
    MAX_TOOL_ROUNDS,
    SYSTEM_PROMPT,
    TOOL_RESULT_CAP_CHARS,
)
from dormy.telegram.tools import TOOL_SCHEMAS, execute_tool


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    round: int


@dataclass
class TurnResult:
    user_message: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    reply: str = ""
    rounds_used: int = 0
    duration_s: float = 0.0
    error: str | None = None


async def run_one_turn(user_message: str) -> TurnResult:
    """One synthetic Telegram turn — system prompt + user msg, run loop."""
    start = time.monotonic()
    out = TurnResult(user_message=user_message)

    try:
        client = get_openrouter_client()
    except RuntimeError as e:
        out.error = f"no OpenRouter key: {e}"
        out.duration_s = time.monotonic() - start
        return out

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    for round_idx in range(MAX_TOOL_ROUNDS):
        out.rounds_used = round_idx + 1
        try:
            resp = await client.chat.completions.create(
                model=CHAT_MODEL,
                messages=messages,  # type: ignore[arg-type]
                tools=TOOL_SCHEMAS,  # type: ignore[arg-type]
                tool_choice="auto",
                max_tokens=CHAT_MAX_TOKENS,
                temperature=CHAT_TEMPERATURE,
            )
        except Exception as e:
            out.error = f"chat.completions failed in round {round_idx}: {e}"
            break

        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []

        if not tool_calls:
            out.reply = (msg.content or "").strip()
            break

        # Match production bot's assistant-message shape so the model can
        # bind tool_call_ids on its next turn.
        messages.append(
            {
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
        )

        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            out.tool_calls.append(
                ToolCall(name=tc.function.name, args=args, round=round_idx)
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

    if not out.reply and not out.error:
        out.reply = "[no reply — loop exhausted]"

    out.duration_s = time.monotonic() - start
    return out


@dataclass
class Case:
    name: str
    user_message: str
    validate: Callable[[TurnResult], tuple[bool, str]]


def _has_tool(r: TurnResult, name: str) -> bool:
    return any(tc.name == name for tc in r.tool_calls)


def _has_skill(r: TurnResult, skill_name: str) -> bool:
    for tc in r.tool_calls:
        if tc.name == "run_skill" and tc.args.get("name") == skill_name:
            return True
    return False


def _reply_contains_any(r: TurnResult, needles: list[str]) -> bool:
    body = r.reply.lower()
    return any(n.lower() in body for n in needles)


def validate_cold_email(r: TurnResult) -> tuple[bool, str]:
    if r.error:
        return False, f"errored: {r.error}"
    if not _has_skill(r, "gtm-cold-email"):
        return False, f"expected run_skill(gtm-cold-email), got {[t.name for t in r.tool_calls]}"
    # Reply should contain target name OR email-structure markers (en or zh).
    # Bot answers in user's language (zh here), so validate both.
    if not _reply_contains_any(
        r,
        [
            "sequoia",
            "subject",
            "主题",
            "邮件",
            "你好",
            "hi ",
            "hello",
        ],
    ):
        return False, "reply lacks Sequoia/email-structure markers"
    return True, "OK"


def validate_page_cro(r: TurnResult) -> tuple[bool, str]:
    if r.error:
        return False, f"errored: {r.error}"
    if not _has_tool(r, "fetch_page"):
        return False, f"expected fetch_page call, got {[t.name for t in r.tool_calls]}"
    if not _has_skill(r, "gtm-page-cro"):
        return False, f"expected run_skill(gtm-page-cro), got {[t.name for t in r.tool_calls]}"
    # Real heydormy.ai content markers — quoted headline, CTA labels, or
    # site-specific terms. Multilingual since bot answers in user's language.
    page_markers = [
        "heydormy",
        "fundraising",
        "founder",
        "telegram",
        "claude code",
        "get started",
        "request telegram",
        "专注建产品",  # actual headline phrase
        "融资",
        "创业者",
        "创始人",
        "投资人",
    ]
    if not _reply_contains_any(r, page_markers):
        return False, "reply doesn't reference real heydormy.ai content"
    return True, "OK"


def validate_recent_funding(r: TurnResult) -> tuple[bool, str]:
    if r.error:
        return False, f"errored: {r.error}"
    if not _has_tool(r, "recent_funding"):
        return False, f"expected recent_funding, got {[t.name for t in r.tool_calls]}"
    return True, "OK"


def validate_web_search(r: TurnResult) -> tuple[bool, str]:
    if r.error:
        return False, f"errored: {r.error}"
    if not _has_tool(r, "web_search"):
        return False, f"expected web_search, got {[t.name for t in r.tool_calls]}"
    return True, "OK"


def validate_chat_no_tools(r: TurnResult) -> tuple[bool, str]:
    if r.error:
        return False, f"errored: {r.error}"
    if r.tool_calls:
        return False, f"expected no tools, got {[t.name for t in r.tool_calls]}"
    if not r.reply:
        return False, "no reply"
    return True, "OK"


CASES: list[Case] = [
    Case(
        name="cold_email",
        user_message=(
            "帮我写一封 cold email 给 Sequoia,我做 AI infra Series A,"
            "产品是 LLM 推理加速"
        ),
        validate=validate_cold_email,
    ),
    Case(
        name="page_cro_with_url",
        user_message=(
            "我的 landing page 是 https://www.heydormy.ai,"
            "你帮我看看 CRO 怎么改"
        ),
        validate=validate_page_cro,
    ),
    Case(
        name="recent_funding",
        user_message="AI infra 最近 30 天有哪些公司融资了?",
        validate=validate_recent_funding,
    ),
    Case(
        name="web_search_company",
        user_message="sekureclaw.ai 是做什么的?",
        validate=validate_web_search,
    ),
    Case(
        name="chat_no_tools",
        user_message="你好",
        validate=validate_chat_no_tools,
    ),
]


def _format_tool_call(tc: ToolCall, max_arg_len: int = 200) -> str:
    args = json.dumps(tc.args, ensure_ascii=False)
    if len(args) > max_arg_len:
        args = args[:max_arg_len] + "..."
    return f"  round{tc.round}: {tc.name}({args})"


def _format_reply(reply: str, cap: int = 600) -> str:
    if len(reply) <= cap:
        return reply
    return reply[:cap] + f"\n  ... [truncated, {len(reply)} total chars]"


async def main() -> int:
    print("=" * 70)
    print(f"E2E Telegram self-test — {len(CASES)} cases")
    print(f"model={CHAT_MODEL}  max_rounds={MAX_TOOL_ROUNDS}")
    print("=" * 70)

    results: list[tuple[Case, TurnResult, bool, str]] = []

    for i, case in enumerate(CASES, 1):
        print(f"\n=== case {i}/{len(CASES)}: {case.name} ===")
        print(f"user: {case.user_message}")
        result = await run_one_turn(case.user_message)
        passed, reason = case.validate(result)
        results.append((case, result, passed, reason))

        if result.tool_calls:
            print("tool calls:")
            for tc in result.tool_calls:
                print(_format_tool_call(tc))
        else:
            print("tool calls: (none)")

        print(f"reply ({len(result.reply)} chars):")
        for line in _format_reply(result.reply).splitlines() or [""]:
            print(f"  {line}")

        print(
            f"verdict: {'PASS' if passed else 'FAIL'} "
            f"({reason}) — {result.rounds_used} round(s), "
            f"{result.duration_s:.1f}s"
        )

    print("\n" + "=" * 70)
    passed_count = sum(1 for *_, p, _ in results if p)
    print(f"SUMMARY: {passed_count}/{len(results)} pass")
    for case, _r, p, reason in results:
        mark = "✓" if p else "✗"
        print(f"  {mark} {case.name}: {reason}")
    print("=" * 70)

    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
