# `/dormy research-vc <name>`

## Goal

Produce a tight, actionable VC research dossier for one investor or firm:
thesis, recent portfolio, partner profiles, signal on whether they're
deploying right now, and (if Dormy MCP is wired in) cross-reference with
your Inner Circle + your past notes.

## Paradigm

**Hybrid:** pure-client web research + optional MCP cross-reference.

- **Always run** (client-side, your Claude Code tokens):
  - Web research (WebFetch + WebSearch on the VC's site, blog, recent posts)
  - LLM summarization
- **Run if Dormy MCP is configured** (MCP-backed, server-side data):
  - `mcp_dormy_find_investors` to check if the VC is in your Inner Circle
    or recent matches
  - `mcp_dormy_memory_recall` for your own past notes about this VC

If Dormy MCP isn't installed, skip the MCP steps and continue. The skill
output will note what's missing.

## Inputs

```
/dormy research-vc <name>

Examples:
  /dormy research-vc "Sequoia Capital"
  /dormy research-vc "Martin Casado"
  /dormy research-vc "a16z infra"
```

The name can be a firm, a partner, or a thesis area + firm. Be flexible.

## Steps

Claude Code, run the following in order. Stream observations as you go;
don't wait until the end to report.

### 1. Resolve the name

If the input is ambiguous (e.g. "Sequoia"), pick the most likely target
(Sequoia Capital US first, then Sequoia China if context suggests). Note
the assumption in your output.

### 2. Web research (client-side, ~5 fetches max)

Run WebFetch / WebSearch on:

- Their primary firm website (about, team, portfolio pages)
- Their most recent blog post or partner letter
- Recent news (last 90 days): "<name> portfolio 2026" / "<name> new fund"
- Their main partner's Twitter / LinkedIn if they have a public presence
- One recent portfolio company announcement to triangulate active stage
  + sector

If a fetch fails (paywalled, 404, etc.), note it and continue. Don't burn
fetches retrying.

### 3. Cross-reference with Dormy MCP (optional)

If `mcp__dormy__find_investors` is available:

```
mcp__dormy__find_investors(sector=null, stage=null, n=20)
```

Look for the VC name in `inner_circle_active` or `inner_circle_resting`.
If found:
- Note the tier (`⭐⭐` active vs `⭐` resting)
- Surface their `personal_notes` and `warm_intro_path` (Inner Circle private)

If `mcp__dormy__memory_recall` is available:

```
mcp__dormy__memory_recall(query="<vc-name>", n=10)
```

Pull your past observations or notes mentioning this VC.

### 4. Synthesize

Produce a single markdown report with the structure below. Every claim
must be backed by either a web source URL or a Dormy MCP retrieval.

## Output format

```markdown
# Research: {VC name}

> {one-line bottom-line: are they live and worth the outreach right now?}

## Thesis & focus
{2-3 sentences. Stage range, sector range, geographic focus, check size if known.}

## Recent activity (last 90 days)
- {date} — {portfolio company / fund news / partner public take}
  Source: {url}
- ...

## People to know
- **{Partner name}** — {role}. {one observation about their public lens}
  - {link to recent post / talk / portfolio bet they led}

## Inner Circle hit (if any)
{From Dormy MCP find_investors. If no hit: "Not in Inner Circle.")
- Tier: {⭐⭐ active | ⭐ resting | not present}
- Warm intro path: {value or "none on file"}
- Your past notes: {value or "none"}

## Your prior observations (if any)
{From Dormy MCP memory_recall. List relevant past observations with their kind + observed date.}

## Recommended next move
{One sentence. "Cold email <partner> referencing <recent post>" /
"Ask <intro> for a warm intro" / "Wait — they're slow on this stage right now".}

---
*Sources: {count} web fetches, {count} MCP calls.*
*Skipped MCP cross-reference: {reason if applicable}.*
```

## MCP fallback

If neither MCP tool is available, the report skips "Inner Circle hit" and
"Your prior observations" sections and adds a footer:

> _Dormy MCP not configured — install it via `claude mcp add dormy ...`
> for Inner Circle hits and your private notes. See https://heydormy.ai._

## Cost notes

- **Without MCP:** ~5 WebFetch + 1-2 WebSearch + Sonnet summary. Pure
  Claude Code tokens, no Dormy server cost.
- **With MCP:** + 2 MCP calls (find_investors, memory_recall). MCP server
  cost is ~$0.001 per call against Supabase + your BYOK key. Negligible.

## Anti-patterns

- ❌ Don't fetch more than 5-6 URLs. Diminishing returns vs token cost.
- ❌ Don't write a "comprehensive overview" — the user wants the actionable
  cut. Three things they didn't already know.
- ❌ Don't hedge ("seems like", "maybe"). Either you found a signal or you
  didn't.
- ❌ Don't repeat the firm's marketing tagline as analysis.
