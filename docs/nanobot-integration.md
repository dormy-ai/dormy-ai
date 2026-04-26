# Nanobot Integration — Step 4 Plan

> **Status:** starter wired (this document + `docs/nanobot-config-example.json`).
> Production deployment (Telegram bot at `@HeyDormyBot`) lands once OpenRouter
> billing is set up for the dormy_router mode and Railway deploy targets are
> finalized.

## What we're integrating

- **Dormy MCP server** (this repo, `dormy.mcp.server`): exposes 6 tools
  (`dormy_profile_set`, `dormy_scan_product`, `dormy_find_investors`,
  `dormy_draft_intro`, `dormy_watch_vcs`, `dormy_memory_recall`).
- **Nanobot** ([HKUDS/nanobot](https://github.com/HKUDS/nanobot)): agent
  runtime providing chat-channel multiplexing (Telegram / Discord / WeChat
  / Slack / etc.), session management, and tool dispatch.

Nanobot consumes Dormy MCP **as one of its `mcp_servers` entries**. No code
changes needed in `dormy-ai` — the existing MCP server (stdio or HTTP) is
already MCP-spec-compliant. Wiring is pure config.

## The architecture

```
                              ┌──────────────────────────────────────┐
                              │   Founders (humans)                  │
                              └──┬─────────────┬─────────────┬──────┘
                                 │             │             │
                          Telegram        Discord        WeChat (future)
                                 │             │             │
                                 ▼             ▼             ▼
                              ┌──────────────────────────────────────┐
                              │  Nanobot agent runtime               │
                              │  (Railway service)                   │
                              │  - 13+ chat channels                 │
                              │  - per-(channel,chat_id) sessions    │
                              │  - LLM provider routing              │
                              └──────────────┬───────────────────────┘
                                             │ MCP JSON-RPC over stdio/HTTP
                                             ▼
                              ┌──────────────────────────────────────┐
                              │  Dormy MCP server                    │
                              │  (Railway service or stdio subproc)  │
                              │  - BYOK auth (Authorization: Bearer) │
                              │  - 6 tools (mock → real Week 3-4)    │
                              │  - fire-and-forget extractor hooks   │
                              └──────────────┬───────────────────────┘
                                             │
                                             ▼
                              ┌──────────────────────────────────────┐
                              │  Supabase Postgres                   │
                              │  - users / contacts / knowledge      │
                              │  - user_observations                 │
                              └──────────────────────────────────────┘
```

Parallel "machine entry" path is unchanged: Claude Code / Cursor connect
to the same Dormy MCP server directly (without nanobot in the middle), via
either stdio (local) or HTTP (`mcp.heydormy.ai`).

## Two deployment modes

### Mode A — local dev (stdio)

Nanobot spawns Dormy MCP as a stdio subprocess. Useful for testing the
Telegram channel against a developer's local Dormy code without deploying.

`~/.nanobot/config.json`:

```json
{
  "tools": {
    "mcp_servers": {
      "dormy": {
        "type": "stdio",
        "command": "uv",
        "args": [
          "run", "--directory",
          "/Users/bei/Documents/AI_Dev/dormy_cli/dormy-ai",
          "python", "-m", "dormy.mcp.server"
        ],
        "env": {
          "DORMY_DATABASE_URL": "postgres://...",
          "DORMY_OPENAI_API_KEY": "sk-proj-...",
          "DORMY_USER_ID": "<your-uuid>"
        }
      }
    }
  }
}
```

Nanobot tool dispatch automatically prefixes Dormy tools as
`mcp_dormy_dormy_profile_set`, `mcp_dormy_dormy_find_investors`, etc.
(Format: `mcp_<server>_<tool>`.)

### Mode B — production (HTTP, BYOK)

Both nanobot and Dormy MCP run as Railway services. Nanobot connects to
Dormy MCP over HTTPS, passing the founder's BYOK OpenRouter key in the
`Authorization` header.

`~/.nanobot/config.json` (or Railway env-driven):

```json
{
  "tools": {
    "mcp_servers": {
      "dormy": {
        "type": "streamableHttp",
        "url": "https://mcp.heydormy.ai/mcp",
        "headers": {
          "Authorization": "Bearer ${USER_OPENROUTER_KEY}"
        },
        "tool_timeout": 60
      }
    }
  }
}
```

The interesting wrinkle here: nanobot needs to vary `Authorization` per
**Telegram chat_id**, because each user brings their own OpenRouter key.
Two options:

1. **Single shared bot, single MCP key** — Dormy MCP is hosted-and-paid by
   us; observations attribute to the BYOK key hash regardless. Simpler;
   matches the `dormy_router` business model from `DORMY_BLUEPRINT.md`.
2. **Per-user key in nanobot session** — each founder onboards by sending
   their OpenRouter key to the bot once, nanobot stores it per-chat_id,
   injects on every MCP call. More work, true BYOK end-to-end.

v0.1 takes path **(1)**. v0.2 if a privacy-sensitive cohort wants
self-hosted, we publish the `Mode A` config + let them run their own.

## Pieces still pending

| Piece | Status | Owner |
|---|---|---|
| Dormy MCP server (BYOK middleware) | ✅ live (PR #3) | shipped |
| `users.api_key` lookup / lazy create | ✅ live (PR #6) | shipped |
| MCP tool fire-and-forget extractor hooks | ✅ live (PR #7) | shipped |
| Embedder pinned base_url (vs env hijack) | ✅ live (PR #8) | shipped |
| Extractor prompt polish (em-dash, rubric, voice) | ✅ live (PR #9) | shipped |
| Nanobot config example + integration docs | ✅ this PR | shipped |
| **Nanobot deploy to Railway** | ⏳ | next session |
| **Telegram bot production token + register** | ⏳ | next session (after BotFather token revocation of the spike token) |
| **`@HeyDormyBot` brand name registration on BotFather** | ⏳ | next session |
| **Dormy `dream.intervalH=99999` + `disabled_skills=["memory"]`** in nanobot config | ⏳ | next session (when we configure Railway env) |
| **Watcher cron via nanobot.cron** | ⏳ | when watcher tool moves off mock |
| **Daily 03:00 batch via nanobot.cron** | ⏳ | optional — current MCP-tool-hook path covers fire-and-forget already |

## Proof-of-concept smoke test (verified 2026-04-26)

Verified locally that adding Dormy MCP to `~/.nanobot/config.json` makes
all 6 tools visible to nanobot's agent loop. **Zero dormy-ai code change
required** — wiring is purely the config block at
`docs/nanobot-config-example.json`.

Steps run:

1. Patched `~/.nanobot/config.json` with the `tools.mcp_servers.dormy`
   stdio entry (pointing at the local checkout).
2. Asked nanobot agent: *"List every tool name available to you. Output
   ONLY a comma-separated list of tool names, no commentary."*

Output (18 tools — 12 nanobot builtins + 6 dormy):

```
exec, glob, grep, list_dir, message, notebook_edit, read_file, write_file,
cron, spawn, web_fetch, web_search,
mcp_dormy_dormy_draft_intro, mcp_dormy_dormy_find_investors,
mcp_dormy_dormy_memory_recall, mcp_dormy_dormy_profile_set,
mcp_dormy_dormy_scan_product, mcp_dormy_dormy_watch_vcs
```

Naming scheme: nanobot prefixes external MCP tools as
`mcp_<server>_<tool>`. Dormy registered its tools without a `dormy_`
prefix in the names (the prefix is in the `register-as` server name), so
the final namespaced names end up double-`dormy_` — `mcp_dormy_dormy_*`.
We can rename Dormy's tools to drop the `dormy_` prefix in a future
cleanup pass; not blocking.

## Why this is one-night-doable as a starter

Step 4 in the plan file estimated ~1 week. The bulk of that estimate was
"wire dormy/engine business logic into nanobot skills". But **Dormy already
exposes its functionality as MCP**, and nanobot natively consumes MCP via
`mcp_servers` config. There is no skill-rewriting work — nanobot just sees
the tools.

The remaining ~1 week of Step 4 work is *deployment + brand polish*:
Railway service setup, production Telegram bot registration with the right
brand name, env var management, observability. None of that is dormy-ai
code; all of it is platform/ops work.
