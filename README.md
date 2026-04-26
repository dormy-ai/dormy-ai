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

## Architecture

Built on top of [nanobot-ai](https://github.com/HKUDS/nanobot) (v0.1.5+). See [DORMY_BLUEPRINT.md](../dormy_cli/DORMY_BLUEPRINT.md) for full design rationale.

## License

Apache 2.0.
