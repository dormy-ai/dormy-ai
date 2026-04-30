"""Telegram bot tool registry — schemas + executors for OpenRouter function calling.

The Telegram bot uses OpenAI-compatible chat completions through OpenRouter.
When we pass `tools=TOOL_SCHEMAS` + `tool_choice="auto"`, the model can emit
tool_call objects instead of plain text. The bot's chat loop then dispatches
those calls through `execute_tool()` which runs the same async executors the
MCP server uses (single source of truth — both surfaces share implementation).

Adding a new tool:
1. Add an entry to TOOL_SCHEMAS with the OpenAI function-calling JSON schema
2. Add a branch in execute_tool() that calls the corresponding `run_*` function
3. (Optional) Update the bot's system prompt so the model knows when to use it
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from dormy.mcp.tools.find import run_find_investors
from dormy.mcp.tools.find_gtm import run_find_gtm
from dormy.mcp.tools.page_fetch import run_fetch_page
from dormy.mcp.tools.recent_funding import run_recent_funding
from dormy.mcp.tools.web_search import run_web_search
from dormy.skills.registry import VALID_CATEGORIES, registry
from dormy.skills.runner import run_skill
from dormy.telemetry import log_tool_call, maybe_alert_on_error


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Real-time web search via Tavily. Use when the user asks about a "
                "specific company, website, person, or anything time-sensitive "
                "they referenced (e.g. 'what does sekureclaw.ai do?', "
                "'who's been raising lately', 'what's a16z investing in this "
                "month'). Returns a synthesized answer plus ranked source snippets "
                "with URLs. Don't claim you can't access the web — you can."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language search query.",
                    },
                    "n": {
                        "type": "integer",
                        "description": "Number of source hits to return (1-10).",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5,
                    },
                    "depth": {
                        "type": "string",
                        "enum": ["basic", "advanced"],
                        "description": "'basic' (~1s) or 'advanced' (slower, deeper).",
                        "default": "basic",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recent_funding",
            "description": (
                "Query Dormy's curated funding-rounds database (TechCrunch + "
                "36kr + Pandaily + startups.gallery, refreshed daily). Use when "
                "the user wants real funding data — 'who just raised in AI infra', "
                "'show me recent Series A rounds', 'AI infra deals last 30 days'. "
                "Don't fabricate from training data; call this instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sector": {
                        "type": "string",
                        "description": (
                            "Loose substring match against the company's sector. "
                            "'AI' will hit 'AI', 'AI Infra', 'AI Agents', etc. "
                            "Omit to return all sectors."
                        ),
                    },
                    "stage": {
                        "type": "string",
                        "description": (
                            "Round stage: seed | a | b | c | growth | late. "
                            "Omit to return all stages."
                        ),
                    },
                    "days": {
                        "type": "integer",
                        "description": "Look-back window in days (1-365).",
                        "minimum": 1,
                        "maximum": 365,
                        "default": 30,
                    },
                    "n": {
                        "type": "integer",
                        "description": "Max events to return (1-50).",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 10,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_investors",
            "description": (
                "Look up the user's Inner Circle of VCs / angels (role: vc | "
                "angel) from Supabase, filtered by sector and/or stage. Use "
                "when the user is asking who to raise from, who to send a "
                "deck to, who in their network is investing in X. Returns "
                "three tiers: inner_circle_active (recently active), "
                "inner_circle_resting (quiet), external_active (unknown, "
                "needs warm intro). Inner entries include personal_notes + "
                "warm_intro_path. For GTM advisors / agencies / operators, "
                "use find_gtm instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sector": {
                        "type": "string",
                        "description": (
                            "Sector tag exactly as stored in the contact's "
                            "sectors[] array, e.g. 'ai-infra', 'fintech', "
                            "'consumer'. Omit to match any sector."
                        ),
                    },
                    "stage": {
                        "type": "string",
                        "enum": ["pre-seed", "seed", "A", "B", "growth"],
                        "description": "Round stage. Omit to match any stage.",
                    },
                    "n": {
                        "type": "integer",
                        "description": "Max results per tier (1-20).",
                        "minimum": 1,
                        "maximum": 20,
                        "default": 5,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_gtm",
            "description": (
                "Look up the user's Inner Circle of GTM resources — "
                "agencies, advisors, operators, founder peers (role: "
                "gtm-advisor | operator | founder-peer) from Supabase. Use "
                "when the user is asking for help with launch / content / "
                "growth / branding / UGC / pricing / hiring / dev-rel. "
                "Returns matches with personal_notes + warm_intro_path. "
                "For investors, use find_investors instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sector": {
                        "type": "string",
                        "description": (
                            "Focus area, e.g. 'ai', 'consumer-tech', "
                            "'fintech', 'edtech'. Omit to match any."
                        ),
                    },
                    "tag": {
                        "type": "string",
                        "description": (
                            "Tag from contact's tags[], e.g. 'ai-ugc', "
                            "'creative-agency', 'pricing', 'tiktok'. "
                            "Omit to match any."
                        ),
                    },
                    "n": {
                        "type": "integer",
                        "description": "Max results (1-20).",
                        "minimum": 1,
                        "maximum": 20,
                        "default": 5,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": (
                "Fetch a public URL and extract its title + meta "
                "description + h1/h2 headings + cleaned body text. Use "
                "BEFORE run_skill for any playbook that critiques a URL "
                "(gtm-page-cro, gtm-seo-audit, gtm-competitor-profiling, "
                "gtm-competitor-alternatives, gtm-form-cro). Without "
                "this, the playbook has nothing concrete to critique. "
                "Don't claim you can't see web pages — you can fetch them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": (
                            "Full URL with http:// or https:// scheme."
                        ),
                    },
                    "max_chars": {
                        "type": "integer",
                        "minimum": 500,
                        "maximum": 40000,
                        "default": 12000,
                        "description": "Cap on body text length.",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": (
                "List Dormy's curated playbook library (42 skills covering "
                "GTM + fundraising). Each skill is a markdown framework "
                "(cold-email, page-cro, pricing-strategy, customer-research, "
                "etc.) the LLM can run via run_skill. Call this first to "
                "discover relevant skills before run_skill. Filter by "
                "category to narrow the list."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": VALID_CATEGORIES,
                        "description": (
                            "Optional filter. icp = customer/ICP research; "
                            "copy = cold email + copywriting; cro = "
                            "conversion / landing-page optimization; seo; "
                            "distribution = paid + social + community; "
                            "growth = lead gen + retention; strategy = "
                            "pricing + launch + content; foundations = "
                            "analytics + AB testing; fundraising = VC research."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_skill",
            "description": (
                "Execute one Dormy skill. Loads the skill's markdown "
                "framework as system prompt and runs a single LLM "
                "completion. Use after list_skills to pick a name. "
                "Pass a paragraph of context as `input` — the user's "
                "specific situation, target, constraints, voice — not "
                "a 1-line query. Returns markdown."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Skill slug from list_skills, e.g. "
                            "'gtm-cold-email', 'gtm-page-cro', "
                            "'gtm-pricing-strategy'."
                        ),
                    },
                    "input": {
                        "type": "string",
                        "description": (
                            "Full paragraph of context: situation + target "
                            "+ constraints + voice notes. Quality of input "
                            "drives quality of output."
                        ),
                    },
                    "model": {
                        "type": "string",
                        "description": (
                            "Optional override, e.g. "
                            "'anthropic/claude-sonnet-4-6' for complex "
                            "critique. Default: claude-haiku-4-5."
                        ),
                    },
                },
                "required": ["name", "input"],
            },
        },
    },
]


async def _dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Inner case-block dispatcher. Returns the tool's result dict, or
    `{"error": ...}` if the name is unknown. May raise on tool failure —
    the wrapper translates that into a telemetry-logged error result."""
    if name == "web_search":
        result = await run_web_search(
            query=args.get("query", ""),
            n=int(args.get("n", 5)),
            depth=str(args.get("depth", "basic")),
            include_answer=True,
        )
        return result.model_dump()
    if name == "recent_funding":
        result = await run_recent_funding(
            sector=args.get("sector"),
            stage=args.get("stage"),
            days=int(args.get("days", 30)),
            n=int(args.get("n", 10)),
        )
        return result.model_dump()
    if name == "find_investors":
        result = await run_find_investors(
            sector=args.get("sector"),
            stage=args.get("stage"),
            n=int(args.get("n", 5)),
        )
        return result.model_dump()
    if name == "find_gtm":
        result = await run_find_gtm(
            sector=args.get("sector"),
            tag=args.get("tag"),
            n=int(args.get("n", 5)),
        )
        return result.model_dump()
    if name == "fetch_page":
        result = await run_fetch_page(
            url=str(args.get("url", "")),
            max_chars=int(args.get("max_chars", 12000)),
        )
        return result.model_dump()
    if name == "list_skills":
        category = args.get("category")
        entries = (
            registry.list_by_category(category)
            if category
            else registry.list_all()
        )
        return {
            "category": category,
            "count": len(entries),
            "skills": [
                {
                    "name": e.name,
                    "category": e.category,
                    "description": e.description,
                }
                for e in entries
            ],
            "available_categories": VALID_CATEGORIES,
        }
    if name == "run_skill":
        result = await run_skill(
            name=str(args.get("name", "")),
            input=str(args.get("input", "")),
            model=args.get("model"),
        )
        return result.model_dump()
    return {"error": f"unknown tool: {name}"}


def _classify_outcome(result: dict[str, Any]) -> tuple[str, str | None]:
    """Inspect a dispatch result; return (status, error_msg)."""
    if "error" in result:
        return "error", str(result["error"])
    if result.get("data_source") == "error":
        return "error", str(result.get("note") or "tool returned data_source=error")
    return "ok", None


async def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call + record telemetry. Returns a JSON-serializable
    dict. Errors come back as `{"error": ...}` (or a result with
    `data_source="error"`) so the LLM can decide whether to apologize,
    retry, or fall back. Telemetry is fire-and-forget — observability
    failure never breaks the user reply path.
    """
    start = time.monotonic()
    try:
        result = await _dispatch(name, args)
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        err = f"{name} failed: {e}"
        logger.warning(f"telegram tool {name} raised: {e}")
        log_tool_call(
            source="telegram",
            tool_name=name,
            status="error",
            latency_ms=latency_ms,
            error_msg=err,
            args=args,
        )
        await maybe_alert_on_error("telegram", name, err)
        return {"error": err}

    latency_ms = int((time.monotonic() - start) * 1000)
    status, error_msg = _classify_outcome(result)
    log_tool_call(
        source="telegram",
        tool_name=name,
        status=status,
        latency_ms=latency_ms,
        error_msg=error_msg,
        args=args,
    )
    if status == "error":
        await maybe_alert_on_error("telegram", name, error_msg)
    return result
