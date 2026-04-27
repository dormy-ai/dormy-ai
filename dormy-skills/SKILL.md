---
name: dormy
description: |
  AI copilot skills for super founders, covering BOTH fundraising and GTM.
  Each command is a workflow Claude Code can run on your behalf — some pure
  client-side (web research, drafting, file editing), some calling the
  Dormy MCP server for private data (Inner Circle contacts, knowledge base,
  watchers, founder profile).

  Trigger this skill for: VC research, drafting cold intros, fundraising
  prep, pitch reviews, deal flow digests, founder profile setup, watcher
  registration — AND for GTM workflows: ICP analysis, copywriting, cold
  email, landing-page CRO, SEO audits, pricing & launch strategy, customer
  research, competitor profiling.
  Skip for: anything outside fundraising / GTM (e.g. "fix this React bug").
license: Apache 2.0 (Dormy code) + MIT (GTM skills derived from coreyhaines31/marketingskills)
---

# Dormy

AI copilot for super founders, exposed as a set of Claude Code skills.
Two domains, equal weight:

- **Fundraising** — investors, intros, pitch positioning, deal timing
- **GTM** — ICP & positioning, copy & cold outreach, landing-page CRO,
  SEO/AI-SEO, pricing & launches

Two paradigms coexist deliberately:

- **Pure-client skills** — run entirely in your Claude Code session. Use your
  Claude Code tokens. No Dormy server round-trip. Good for: web research,
  pitch reviews, intro drafting from scratch.
- **MCP-backed skills** — call the Dormy MCP server (`mcp.heydormy.ai`) for
  private data: Inner Circle contacts, founder profile, knowledge base,
  user observations, active watchers. Server handles auth + multi-tenancy.

Most useful skills are *hybrid*: do client-side web research, then cross-
reference with Dormy server data. The skill markdown for each command
documents which paradigm it uses and what it costs.

> **GTM skills attribution:** the `gtm-*` commands below are derived from
> [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills)
> by Corey Haines (MIT license). Source files vendored verbatim under
> `sources/marketingskills/`; Dormy-flavored adaptations live in `reference/`.
> Sync policy: quarterly manual review. See `sources/UPSTREAM.md`.

## Commands — Fundraising

| Command | Paradigm | What it does |
|---|---|---|
| [`/dormy research-vc <name>`](reference/research-vc.md) | Pure client → optional MCP cross-ref | Deep research on a VC: thesis, portfolio, recent activity, partner profiles. If Dormy MCP is configured, also pulls Inner Circle hits + your prior notes. |
| [`/dormy prep-week`](reference/prep-week.md) | Hybrid skill + MCP | Friday-afternoon fundraising prep digest: recent VC activity in your sectors, Inner Circle pings, draft this week's outbound. Calls `find_investors` + `memory_recall` + web research. |

## Commands — GTM (40 skills)

All `gtm-*` skills are hybrid: client-side framework application + optional
`memory_recall(tags=['gtm', '<category>'])` for cross-skill context.

### Customer / ICP

| Command | What it does |
|---|---|
| `/dormy gtm-customer-research` | Run customer research interviews, synthesize Jobs-to-be-Done, surface activation triggers |
| `/dormy gtm-competitor-profiling` | Profile competitors: positioning, pricing, GTM motion, differentiation gaps |
| `/dormy gtm-competitor-alternatives` | Build out the "alternatives" SEO play: pages targeting "X alternatives to <competitor>" queries |
| `/dormy gtm-product-marketing-context` | Build the founder's product marketing context doc (positioning, audience, value props) — root for all other GTM skills |

### Copy / Outreach

| Command | What it does |
|---|---|
| `/dormy gtm-copywriting` | Write conversion-focused copy: headlines, body, CTAs grounded in Made-to-Stick / StoryBrand frameworks |
| `/dormy gtm-copy-editing` | Edit existing copy for clarity, scannability, conversion friction |
| `/dormy gtm-cold-email` | B2B cold email + follow-up sequences that get replies |
| `/dormy gtm-email-sequence` | Lifecycle / nurture email sequences (onboarding, activation, win-back) |
| `/dormy gtm-ad-creative` | Ad headlines + creative concepts for Meta / LinkedIn / Google |

### Conversion / CRO

| Command | What it does |
|---|---|
| `/dormy gtm-page-cro` | Audit + fix a landing page for conversion (above-the-fold, social proof, friction) |
| `/dormy gtm-form-cro` | Reduce form abandonment: field count, ordering, microcopy |
| `/dormy gtm-popup-cro` | Design popups that convert without annoying (timing, offer, exit intent) |
| `/dormy gtm-onboarding-cro` | Onboarding flow audit: time-to-value, activation milestones |
| `/dormy gtm-signup-flow-cro` | Signup flow optimization: friction reduction, social-proof injection |
| `/dormy gtm-paywall-upgrade-cro` | Paywall + upgrade prompt design for SaaS conversion |

### SEO

| Command | What it does |
|---|---|
| `/dormy gtm-seo-audit` | Full technical + content SEO audit |
| `/dormy gtm-ai-seo` | Optimize content + site for AI search engines (Perplexity, ChatGPT, Claude) |
| `/dormy gtm-programmatic-seo` | Plan + scaffold programmatic SEO (template-driven page generation) |
| `/dormy gtm-schema-markup` | Add structured data (JSON-LD) for rich results + AI grounding |
| `/dormy gtm-site-architecture` | Information architecture: hub-and-spoke content, internal linking |

### Distribution

| Command | What it does |
|---|---|
| `/dormy gtm-paid-ads` | Paid ads strategy: budget allocation, audience targeting, creative testing |
| `/dormy gtm-social-content` | Social content calendar + post drafting for X / LinkedIn |
| `/dormy gtm-video` | Video content strategy: YouTube, TikTok, Reels |
| `/dormy gtm-image` | Image / visual asset strategy for marketing |
| `/dormy gtm-community-marketing` | Build + grow community channels (Slack, Discord, forum) |
| `/dormy gtm-directory-submissions` | List in relevant directories (Product Hunt, AppSumo, niche directories) |

### Growth / Funnel

| Command | What it does |
|---|---|
| `/dormy gtm-lead-magnets` | Design lead magnets that match ICP buying intent |
| `/dormy gtm-referral-program` | Referral program design: incentives, mechanics, attribution |
| `/dormy gtm-free-tool-strategy` | Build free tools as top-of-funnel + brand differentiator |
| `/dormy gtm-churn-prevention` | Churn diagnosis + prevention playbook |
| `/dormy gtm-aso-audit` | App Store Optimization audit (iOS / Google Play) |

### Strategy / Positioning

| Command | What it does |
|---|---|
| `/dormy gtm-pricing-strategy` | Pricing tier design, packaging, willingness-to-pay analysis |
| `/dormy gtm-launch-strategy` | Plan a product launch: timeline, channels, sequencing |
| `/dormy gtm-content-strategy` | Content strategy: pillar topics, distribution, repurposing |
| `/dormy gtm-marketing-ideas` | Generate creative marketing ideas when stuck |

### Foundations / Ops

| Command | What it does |
|---|---|
| `/dormy gtm-analytics-tracking` | Set up product + marketing analytics (events, attribution, dashboards) |
| `/dormy gtm-ab-test-setup` | Design A/B tests with statistical rigor |
| `/dormy gtm-marketing-psychology` | Apply marketing psychology principles (cognitive biases, social proof, scarcity) |
| `/dormy gtm-sales-enablement` | Build sales collateral: decks, battlecards, case studies |
| `/dormy gtm-revops` | Revenue operations setup: CRM, lifecycle stages, attribution |

(More commands are easy to add — see "Adding a command" below.)

## Setup

### Pure-client skills (no MCP needed)

Just install the skill bundle. No keys, no server config.

```bash
# Global install
cp -r dormy-skills ~/.claude/skills/dormy
# Or project-local
cp -r dormy-skills .claude/skills/dormy
```

Claude Code auto-discovers it next session. Verify:

```
/dormy
```

(Lists available subcommands.)

### MCP-backed skills (private Dormy data)

Add the Dormy MCP server to your Claude Code MCP config. Two transports:

```bash
# Hosted (BYOK with your OpenRouter key)
claude mcp add dormy --transport http https://mcp.heydormy.ai/mcp \
  -H "Authorization: Bearer <your-openrouter-key>"

# Local stdio (for dev)
claude mcp add dormy --transport stdio \
  -- uv run --directory /path/to/dormy-ai python -m dormy.mcp.server
```

Skills that need MCP will fail gracefully with a hint to install if it's
missing — they don't crash.

## Adding a command

Every command is a single markdown file in `reference/`. Skill discovery
reads the entry-point `SKILL.md` table above; each command's file gives
Claude Code the detailed instructions for that command.

```bash
# 1. Write the command markdown
$EDITOR reference/your-command.md

# 2. Add a row to the table in SKILL.md
# 3. Test locally — re-cp to ~/.claude/skills/dormy/, restart Claude Code
```

A good command file has:

- **Goal** — one sentence
- **Paradigm** — pure client / MCP-backed / hybrid
- **Inputs** — explicit args, with examples
- **Steps** — what Claude Code should do, in order
- **Output format** — structure of the response
- **MCP fallback** (if hybrid) — graceful degradation when server unavailable

See `reference/research-vc.md` for the canonical example.

## Why both skills and MCP?

- **Skills** = client-side workflows. Cheap (your Claude Code tokens), fast
  to ship (markdown only), great for orchestration and one-off research.
- **MCP** = server-side authoritative data + multi-channel (Telegram, etc.)
  + multi-tenant SaaS. Shared truth across all your devices and channels.

Pure skills can't query your private contacts table from another machine.
Pure MCP can't run web research on your Claude Code's tokens. Hybrid — skill
that calls MCP for specific data — gets you both.

See `dormy-ai/docs/nanobot-integration.md` and the master architecture plan
for the full reasoning.
