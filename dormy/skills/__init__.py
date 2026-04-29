"""Server-side skill execution layer.

Exposes the 42 dormy-skills (`dormy-skills/reference/*.md`) to non-Claude-Code
surfaces (MCP HTTP, Telegram bot, future Discord/dashboard) by treating each
markdown as the system prompt for a one-shot LLM completion.

Markdown is the single source of truth: Claude Code skill mode reads the
files directly via slash-command dispatch; server-side surfaces load the
same markdown through `registry.get(name).markdown` and feed it to the
LLM via `runner.run_skill()`. New skills = drop a `.md` in `reference/`.

Phase 1 (this module) handles the 40 pure-prompt GTM skills. The 2 hybrid
fundraising skills (`research-vc` / `prep-week`) work via this fallback
too but lose their multi-step MCP integration; Phase 2 ships native
orchestrators for those.
"""

from __future__ import annotations

from dormy.skills.registry import SkillEntry, registry
from dormy.skills.runner import SkillResult, run_skill

__all__ = ["SkillEntry", "SkillResult", "registry", "run_skill"]
