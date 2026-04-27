# dormy-skills

Claude Code skills for fundraising — companion to the Dormy MCP server.

## What this is

A bundle of Claude Code "skills" (markdown commands) that automate
common fundraising workflows for founders. Some run entirely client-side
(web research, drafting, file editing). Others call the
[Dormy MCP server](https://github.com/dormy-ai/dormy-ai) for private data:
Inner Circle contacts, founder profile, knowledge base, user observations.

## Why both skills and MCP?

[Pbakaus/impeccable](https://github.com/pbakaus/impeccable) showed how a
pure-skill design can replace a lot of "needs a tool" thinking — the
client's own LLM session does the work, no server, no extra token cost.
For fundraising, though, server-side data (the founder's private contacts
table, multi-channel chat across Telegram + Claude Code, multi-tenant
SaaS isolation) is genuinely necessary.

`dormy-skills` is the workflow / orchestration layer that uses the user's
Claude Code session for cheap things (research, drafting, summarization)
and calls the Dormy MCP server only when private data or cross-channel
state is involved.

See [`SKILL.md`](SKILL.md) for the full architecture rationale and
command list.

## Install

```bash
# Global (recommended)
cp -r dormy-skills ~/.claude/skills/dormy
```

Verify:

```
# In a fresh Claude Code session
/dormy
```

## Commands

- `/dormy research-vc <name>` — VC research dossier (pure client + optional MCP cross-ref)
- `/dormy prep-week` — Friday fundraising digest (hybrid, requires MCP)

More to come — see `reference/` for the per-command markdown.

## Adding a command

```bash
$EDITOR reference/your-command.md   # write the spec
$EDITOR SKILL.md                    # add a row to the menu table
cp -r ../dormy-skills ~/.claude/skills/dormy   # re-install
```

Restart Claude Code. New command auto-discovered.

## License

Apache 2.0.
