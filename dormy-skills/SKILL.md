---
name: dormy
description: |
  Fundraising copilot skills for founders. Each command is a workflow Claude Code
  can run on your behalf — some pure client-side (web research, drafting, file
  editing), some calling the Dormy MCP server for private data (Inner Circle
  contacts, knowledge base, watchers). Use whichever shape fits the task.

  Trigger this skill for: VC research, drafting cold intros, fundraising prep,
  pitch reviews, deal flow digests, founder profile setup, watcher registration.
  Skip for: anything outside fundraising / GTM (e.g. "fix this React bug").
license: Apache 2.0
---

# Dormy

Fundraising copilot, exposed as a set of Claude Code skills. Two paradigms
coexist deliberately:

- **Pure-client skills** — run entirely in your Claude Code session. Use your
  Claude Code tokens. No Dormy server round-trip. Good for: web research,
  pitch reviews, intro drafting from scratch.
- **MCP-backed skills** — call the Dormy MCP server (`mcp.heydormy.ai`) for
  private data: Inner Circle contacts, founder profile, knowledge base,
  user observations, active watchers. Server handles auth + multi-tenancy.

Most useful skills are *hybrid*: do client-side web research, then cross-
reference with Dormy server data. The skill markdown for each command
documents which paradigm it uses and what it costs.

## Commands

| Command | Paradigm | What it does |
|---|---|---|
| [`/dormy research-vc <name>`](reference/research-vc.md) | Pure client → optional MCP cross-ref | Deep research on a VC: thesis, portfolio, recent activity, partner profiles. If Dormy MCP is configured, also pulls Inner Circle hits + your prior notes. |
| [`/dormy prep-week`](reference/prep-week.md) | Hybrid skill + MCP | Friday-afternoon fundraising prep digest: recent VC activity in your sectors, Inner Circle pings, draft this week's outbound. Calls `find_investors` + `memory_recall` + web research. |

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
