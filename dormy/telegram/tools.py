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

from typing import Any

from loguru import logger

from dormy.mcp.tools.recent_funding import run_recent_funding
from dormy.mcp.tools.web_search import run_web_search
from dormy.skills.registry import VALID_CATEGORIES, registry
from dormy.skills.runner import run_skill


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


async def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call from the LLM. Returns a JSON-serializable dict.

    Errors are returned as `{"error": "..."}` so the LLM can decide whether
    to apologize, retry with different args, or fall back to a non-tool answer.
    """
    try:
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
    except Exception as e:
        logger.warning(f"telegram tool {name} raised: {e}")
        return {"error": f"{name} failed: {e}"}
    return {"error": f"unknown tool: {name}"}
