# Dormy AI

> Fundraising copilot for founders — MCP + CLI + proactive watchers.

**Live:** https://heydormy.ai

## Status

**v0.1 — in active development (Week 1)**. Not yet published to PyPI.

## What it is

Dormy is an **agent-native** fundraising infrastructure for founders. It exposes curated VC intelligence, deep investor research, and proactive match watchers through MCP and CLI — so agents like Claude Code, Cursor, or your own scripts can call it directly.

## Core tools

- `profile_set` — build a founder/product profile from a URL
- `scan_product` — structured product profile (market, differentiators, risks)
- `find_investors` — Inner Circle ⭐ + Active VC + on-demand deep research
- `draft_intro` — personalized outreach email
- `watch_vcs` — daily VC match pushed via Email/Telegram
- `memory_recall` — RAG retrieval from Dormy's knowledge base

## Tier

| | Free (BYOK) | Pro (Dormy Router) |
|---|---|---|
| MCP / CLI | ✅ | ✅ |
| Self-host | ✅ `docker run` | — |
| Inner Circle basic | ✅ | ✅ |
| MiroThinker deep research | — | ✅ |
| Proactive watchers | — | ✅ |
| Inner Circle `personal_notes` + `warm_intro_path` | — | ✅ |
| Unified router (no key management) | — | ✅ 5% markup |

## Development

```bash
git clone https://github.com/beizhangnina/dormy-ai.git
cd dormy-ai
uv sync
uv run dormy --version
```

### Pre-merge self-test (Telegram + MCP tool changes)

Any PR that touches `dormy/telegram/` or `dormy/mcp/tools/` must pass an
end-to-end self-test before merge — unit tests don't catch how the
production LLM actually chains the tools. The script below mirrors the
bot's `_llm_reply` loop with the same system prompt, tool schemas, and
executors, and runs 5 representative turns against real OpenRouter:

```bash
# Inject Railway env (or set DORMY_OPENROUTER_API_KEY locally):
export DORMY_OPENROUTER_API_KEY=$(railway variables --service dormy-tg --kv \
  | grep '^DORMY_OPENROUTER_API_KEY=' | cut -d= -f2-)
export DORMY_TAVILY_API_KEY=$(railway variables --service dormy-tg --kv \
  | grep '^DORMY_TAVILY_API_KEY=' | cut -d= -f2-)
export DORMY_DATABASE_URL=$(railway variables --service dormy-tg --kv \
  | grep '^DORMY_DATABASE_URL=' | cut -d= -f2-)

uv run python -m scripts.e2e_telegram   # ~60s, ~$0.05 in OpenRouter calls
```

Expect `5/5 pass`. Paste the transcript into the PR description as
evidence. Don't request human QA in Telegram before this is green.

## Architecture

Built on top of [nanobot-ai](https://github.com/HKUDS/nanobot) (v0.1.5+). See [DORMY_BLUEPRINT.md](../dormy_cli/DORMY_BLUEPRINT.md) for full design rationale.

## License

Apache 2.0.
