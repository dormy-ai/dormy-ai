# `/dormy prep-week`

## Goal

A fundraising prep digest for the week ahead: who in your Inner Circle is
worth pinging, what just happened in your sectors, and 2-3 outbound drafts
you can send Monday morning.

This is the canonical *hybrid* skill — orchestrates Dormy MCP private data
calls with client-side web research + LLM synthesis.

## Paradigm

**Hybrid.** Requires Dormy MCP to be configured. If it isn't, the skill
fails fast with a setup hint.

## Inputs

No required args. Optional:

```
/dormy prep-week [--sector <name>] [--stage <name>] [--n <count>]
```

Defaults:
- sector / stage: pulled from your active founder profile via Dormy MCP
- n: 5

## Steps

### 1. Get founder context (MCP)

```
mcp__dormy__find_investors(n=10)
```

This call works without explicit sector/stage because the MCP server reads
your active founder profile. The response gives you Inner Circle ⭐⭐
(active in sector now) + ⭐ (resting), and external_active candidates.

If the call fails because Dormy MCP isn't configured, exit with:

> _This skill requires Dormy MCP. Install with:_
> `claude mcp add dormy --transport http https://mcp.heydormy.ai/mcp -H "Authorization: Bearer <key>"`

### 2. Recent VC activity (web)

For the top 3 firms in `inner_circle_active`:

- WebSearch: "<firm name> investment OR portfolio OR fund last 30 days"
- Pick the most recent signal — a check, a blog post, a podcast appearance.

Also pull the recent_activity field from the MCP response — it's already
denormalized for fast use.

### 3. Your prior notes (MCP)

```
mcp__dormy__memory_recall(query="weekly fundraising context", n=5, kinds=["concern","goal"])
```

Filter to `concern` and `goal` kinds — these are the most useful for
"what's hot this week" prioritization.

### 4. Draft 2-3 outbound emails (client-side)

For 2-3 of the Inner Circle ⭐⭐ contacts that have a fresh signal (recent
investment in your sector, recent public take, etc.), draft a cold-but-
warm outbound email:

- 3 sentences max
- Lead with the specific recent signal (not generic praise)
- One line on your traction tied to their thesis
- One ask (15-min call) — not a long deck attachment

If `mcp__dormy__draft_intro` is available, you can call it — it has
templates tuned to Dormy's voice. Otherwise draft directly with Sonnet.

### 5. Synthesize the digest

Output one markdown digest with the structure below.

## Output format

```markdown
# Fundraising prep — week of {Monday date}

## ⭐⭐ Live this week
- **{Partner, Firm}** ({sector / stage match}) — {recent signal in 1 line}
  - **Suggested move:** {warm intro via X | cold email referencing Y}

## ⭐ On the bench
- {Partner, Firm} — last note from your records: "{quote}". {context: when worth re-engaging}

## Outbound drafts (ready to send)

### Draft 1 — {Partner, Firm}
**Subject:** {subject}
**Body:**
> {3-sentence email}

**Send via:** {warm intro X | cold email at <addr>}

### Draft 2 — ...

## What I noticed this week
{1-3 bullets pulled from your recent observations + this week's signals.}

---
*Generated from {N} MCP calls + {N} web fetches.*
```

## Cost notes

- 1-3 MCP calls (find_investors, memory_recall, optional draft_intro)
- 5-10 WebSearch / WebFetch
- 1 Sonnet synthesis

Total: ~$0.10-0.20 client-side LLM (your Claude Code tokens) + negligible
MCP cost. Run weekly without thinking about it.

## Anti-patterns

- ❌ Don't include partners with no fresh signal — the digest's value is
  filtering, not exhaustiveness.
- ❌ Don't write 5-paragraph emails. Three sentences. Specific. Asking.
- ❌ Don't mention "AI fundraising tool Dormy" in outbound emails — that's
  for your pitch, not your VC outreach.
- ❌ Don't use em-dashes in the email drafts. Voice rule from Dormy's
  design system: commas, colons, semicolons, periods, parentheses.
