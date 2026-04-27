"""GTM MCP tools — landing-page review + cold-outreach drafting.

Two tools, both follow the same pattern:
1. Pull a fresh URL or take a recipient context as input
2. `knowledge_recall` against the GTM playbook RAG (Layer 1) for relevant
   framework excerpts, sub-tagged by category
3. Compose with OpenRouter (BYOK key flows through `get_openrouter_client`)
4. Return a structured Pydantic model

These complement the 40 client-side `gtm-*` Claude Code skills: they're
the high-frequency workflows that benefit from server-side state
(founder profile, Inner Circle, accumulated observations) and that we
want callable from any surface (Claude Code, Cursor, future Telegram
tool-calling).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from loguru import logger
from pydantic import BaseModel, Field

from dormy.knowledge.retrieve import recall as knowledge_recall
from dormy.llm.client import get_openrouter_client
from dormy.memory.hooks import from_mcp_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

# Same lightweight chat model the Telegram bot uses — fast, cheap, good
# enough for structured GTM critique. BYOK billed; if no key in context,
# falls back to settings (CLI dev path).
GTM_MODEL = "anthropic/claude-haiku-4-5"
GTM_MAX_TOKENS = 1500
GTM_TEMPERATURE = 0.3  # bias toward concrete advice over creative riffs

# Conservative cap so we don't dump huge fetched HTML into the LLM
LANDING_PAGE_TEXT_CAP = 8000


class LandingReview(BaseModel):
    url: str
    cro_critique: str = Field(description="Above-the-fold, friction, trust")
    copy_critique: str = Field(description="Headlines, body, CTAs")
    seo_critique: str = Field(description="Title, meta, schema, AI-search")
    rewrites: list[str] = Field(
        default_factory=list,
        description="3-5 concrete rewrite suggestions, each ≤200 chars",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Skill names from the RAG corpus that informed the critique",
    )
    note: str


class OutreachDraft(BaseModel):
    target: str
    intent: str
    short_version: str = Field(description="≤500 chars — DM / pre-LinkedIn")
    medium_version: str = Field(description="≤1000 chars — standard cold email")
    long_version: str = Field(description="~1500 chars — context-heavy")
    hook_rationale: str = Field(
        description="Why this hook for this target/intent — cite framework"
    )
    sources: list[str] = Field(default_factory=list)
    note: str


async def _fetch_landing_text(url: str) -> tuple[str, str | None]:
    """Fetch URL, extract visible text. Returns (text, error_or_none).

    Intentionally simple — a robust extractor lives in dormy-fundingnews;
    here we just need enough text for the LLM to critique. If fetch fails,
    return a clear error string so the tool can degrade gracefully."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(15.0),
            headers={"User-Agent": "Dormy-GTM/1.0 (+https://heydormy.ai)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            text = resp.text
    except Exception as e:  # noqa: BLE001
        return "", f"fetch failed: {e}"

    # Cheap extraction — strip script/style + whitespace. Good enough for
    # critique; if the user wants screenshot-grade analysis they should
    # use `/dormy gtm-page-cro` from Claude Code (Playwright-capable).
    import re

    cleaned = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.S | re.I)
    cleaned = re.sub(r"<style[^>]*>.*?</style>", "", cleaned, flags=re.S | re.I)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:LANDING_PAGE_TEXT_CAP], None


async def _rag_excerpts(query: str, sub_tags: list[str], limit: int = 6) -> tuple[str, list[str]]:
    """Pull GTM playbook excerpts for `sub_tags`. Returns (joined_text, source_titles)."""
    try:
        # Recall once per sub-tag so each playbook gets a chance to surface;
        # the alternative (one big OR query) tends to bias toward whichever
        # category has the most chunks (distribution > foundations > seo).
        all_hits = []
        per_tag = max(2, limit // max(len(sub_tags), 1))
        for sub in sub_tags:
            hits, _mode = await knowledge_recall(
                query=query,
                tags=["gtm", sub],
                limit=per_tag,
            )
            all_hits.extend(hits)
        # Dedupe by source_path
        seen: set[str] = set()
        deduped = []
        for h in all_hits:
            key = h.source_path or h.title or h.excerpt[:50]
            if key not in seen:
                seen.add(key)
                deduped.append(h)
        excerpt_blocks = []
        sources = []
        for h in deduped[:limit]:
            label = h.title or (h.source_path.split("/")[-1] if h.source_path else "playbook")
            excerpt_blocks.append(f"### From: {label}\n\n{h.excerpt}")
            sources.append(label)
        return "\n\n".join(excerpt_blocks), sources
    except Exception as e:  # noqa: BLE001
        logger.warning(f"gtm RAG recall failed: {e}")
        return "", []


def register(mcp: "FastMCP") -> None:
    @mcp.tool(
        description=(
            "Review a landing page for CRO + copy + SEO/AI-SEO. Fetches the "
            "URL, pulls relevant Dormy GTM playbook excerpts (page-cro, "
            "copywriting, seo-audit, ai-seo) as context, and returns a "
            "structured critique with concrete rewrite suggestions."
        ),
    )
    async def gtm_review_landing(
        url: str = Field(description="Landing page URL (must be publicly accessible)"),
        focus: str | None = Field(
            default=None,
            description=(
                "Optional focus: 'cro' / 'copy' / 'seo' / 'all' (default). "
                "When set, the LLM weights that section more heavily."
            ),
        ),
    ) -> LandingReview:
        page_text, fetch_err = await _fetch_landing_text(url)
        if fetch_err:
            result = LandingReview(
                url=url,
                cro_critique="(could not fetch page)",
                copy_critique="(could not fetch page)",
                seo_critique="(could not fetch page)",
                rewrites=[],
                sources=[],
                note=f"⚠️ {fetch_err}",
            )
            from_mcp_call("gtm_review_landing", {"url": url, "focus": focus}, result)
            return result

        rag_text, sources = await _rag_excerpts(
            query=f"landing page review {focus or ''}: {page_text[:300]}",
            sub_tags=["cro", "copy", "seo"],
            limit=6,
        )

        focus_directive = ""
        if focus and focus.lower() in {"cro", "copy", "seo"}:
            focus_directive = f"\n\nWeight the {focus.upper()} section more heavily — that's the user's primary focus."

        prompt = f"""You are reviewing a landing page for a super founder. Use the
playbook excerpts below as your framework — apply them, don't dump them.
Be specific to this page's actual content; vague advice is useless.{focus_directive}

## Page text (first {LANDING_PAGE_TEXT_CAP} chars)

{page_text}

## Relevant playbook excerpts

{rag_text or "(no playbook context — relying on training knowledge)"}

## Your output (use this exact structure)

CRO_CRITIQUE: <2-4 sentences on above-the-fold, social proof, friction, trust signals>
COPY_CRITIQUE: <2-4 sentences on headlines, body clarity, CTAs, value prop>
SEO_CRITIQUE: <2-4 sentences on title/meta, schema, AI-search readiness, internal links>
REWRITES:
- <concrete rewrite 1, ≤200 chars, with the specific element and the better version>
- <concrete rewrite 2>
- <concrete rewrite 3>
- (optional) <concrete rewrite 4-5>"""

        client = get_openrouter_client()
        try:
            resp = await client.chat.completions.create(
                model=GTM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=GTM_MAX_TOKENS,
                temperature=GTM_TEMPERATURE,
            )
            output = (resp.choices[0].message.content or "").strip()
        except Exception as e:  # noqa: BLE001
            logger.error(f"gtm_review_landing LLM call failed: {e}")
            output = ""

        # Light parse — sections may not always come back perfectly formatted,
        # so we degrade gracefully rather than failing the tool call.
        sections = {"CRO_CRITIQUE": "", "COPY_CRITIQUE": "", "SEO_CRITIQUE": ""}
        rewrites: list[str] = []
        current_key: str | None = None
        for line in output.splitlines():
            stripped = line.strip()
            for k in sections:
                if stripped.startswith(f"{k}:"):
                    sections[k] = stripped.split(":", 1)[1].strip()
                    current_key = None
                    break
            else:
                if stripped.startswith("REWRITES:"):
                    current_key = "REWRITES"
                elif current_key == "REWRITES" and stripped.startswith("-"):
                    rewrites.append(stripped.lstrip("- ").strip()[:200])

        result = LandingReview(
            url=url,
            cro_critique=sections["CRO_CRITIQUE"] or "(LLM output not parseable)",
            copy_critique=sections["COPY_CRITIQUE"] or "(LLM output not parseable)",
            seo_critique=sections["SEO_CRITIQUE"] or "(LLM output not parseable)",
            rewrites=rewrites[:5],
            sources=sources,
            note=(
                f"Landing review via {GTM_MODEL}. Grounded in {len(sources)} "
                f"playbook excerpts. Focus: {focus or 'all'}."
            ),
        )
        from_mcp_call("gtm_review_landing", {"url": url, "focus": focus}, result)
        return result

    @mcp.tool(
        description=(
            "Draft a cold outreach message in 3 lengths (short / medium / long). "
            "Pulls from Dormy's cold-email + email-sequence + copywriting "
            "playbooks for hook framing. Use this when the founder needs a "
            "ready-to-send draft, not just guidance."
        ),
    )
    async def gtm_draft_outreach(
        target: str = Field(
            description="Who you're writing to: name + role + company "
            "(e.g. 'Sarah Tavel, Partner at Benchmark')"
        ),
        intent: str = Field(
            description="Outcome you want: 'partnership', 'user-feedback', "
            "'advisor-pitch', 'investor-meeting', 'press-coverage', "
            "'design-partner', or free text"
        ),
        context: str | None = Field(
            default=None,
            description="Optional context: shared connections, specific trigger "
            "events, prior interaction. Sharper hooks come from sharper context.",
        ),
    ) -> OutreachDraft:
        rag_query = f"cold outreach to {target} for {intent}"
        rag_text, sources = await _rag_excerpts(
            query=rag_query,
            sub_tags=["copy"],  # cold-email + email-sequence + copywriting all live here
            limit=5,
        )

        prompt = f"""Draft 3 versions of a cold outreach message to:

**Target:** {target}
**Intent:** {intent}
**Context:** {context or "(none provided)"}

Use the playbook excerpts below as your framework. Hook must be specific
to the target — vague openers like "I noticed your company is growing"
fail. Trigger-event hooks (something the target did this week) > generic
flattery. If context is thin, the hook should be honest about being a
cold reach with a sharp value prop, not pretend a relationship.

## Relevant playbook excerpts

{rag_text or "(no playbook context — relying on training knowledge)"}

## Output format (use this exact structure)

HOOK_RATIONALE: <1-2 sentences explaining the hook angle and which playbook framework you applied>
SHORT_VERSION:
<≤500 chars. DM-style, fits in LinkedIn / Telegram. Hook + one-line pitch + ask.>
MEDIUM_VERSION:
<≤1000 chars. Standard cold email. Hook → why-them → value prop → CTA. Max 4 short paragraphs.>
LONG_VERSION:
<~1500 chars. For high-stakes asks (investor / advisor). Hook → trigger event → value prop → 2-3 specific traction points → ask. Max 6 paragraphs.>"""

        client = get_openrouter_client()
        try:
            resp = await client.chat.completions.create(
                model=GTM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=GTM_MAX_TOKENS,
                temperature=0.7,  # warmer for drafting variation
            )
            output = (resp.choices[0].message.content or "").strip()
        except Exception as e:  # noqa: BLE001
            logger.error(f"gtm_draft_outreach LLM call failed: {e}")
            output = ""

        # Parse the 4 sections. Each starts with a header line; the body is
        # the lines until the next header.
        sections = {
            "HOOK_RATIONALE": "",
            "SHORT_VERSION": "",
            "MEDIUM_VERSION": "",
            "LONG_VERSION": "",
        }
        current: str | None = None
        buf: list[str] = []
        for line in output.splitlines():
            stripped = line.rstrip()
            matched = False
            for k in sections:
                if stripped.startswith(f"{k}:"):
                    if current is not None:
                        sections[current] = "\n".join(buf).strip()
                    current = k
                    rest = stripped.split(":", 1)[1].strip()
                    buf = [rest] if rest else []
                    matched = True
                    break
            if not matched and current is not None:
                buf.append(line)
        if current is not None:
            sections[current] = "\n".join(buf).strip()

        result = OutreachDraft(
            target=target,
            intent=intent,
            short_version=sections["SHORT_VERSION"] or "(LLM output not parseable)",
            medium_version=sections["MEDIUM_VERSION"] or "(LLM output not parseable)",
            long_version=sections["LONG_VERSION"] or "(LLM output not parseable)",
            hook_rationale=sections["HOOK_RATIONALE"]
            or "(no rationale provided)",
            sources=sources,
            note=(
                f"Cold outreach draft via {GTM_MODEL}. Grounded in {len(sources)} "
                f"playbook excerpts (cold-email + email-sequence + copywriting)."
            ),
        )
        from_mcp_call(
            "gtm_draft_outreach",
            {"target": target, "intent": intent, "context": context},
            result,
        )
        return result
