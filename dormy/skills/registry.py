"""Skill registry — discovers and parses `dormy-skills/reference/*.md`.

Frontmatter contract (from upstream marketingskills + dormy adaptations):
  ---
  name: gtm-cold-email
  description: |
    Multi-paragraph trigger-rich description used by the LLM to decide
    whether this skill applies. Treated as `description` for tool listing.
  license: MIT (...)
  ---

Category taxonomy is hardcoded below — keys are skill names, values are
one of: fundraising | icp | copy | cro | seo | distribution | growth |
strategy | foundations. New skills default to "other" if unmapped.

The path to `dormy-skills/reference/` is computed relative to the package:
the directory ships in the repo root alongside `dormy/`, so it resolves
correctly both in local dev (`uv run`) and Railway (whole repo deployed).
Override via `DORMY_SKILLS_PATH` env var if needed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


# Category map — see Explore agent report for the breakdown rationale.
# 42 entries: 2 fundraising + 4 icp + 5 copy + 6 cro + 5 seo + 6 distribution
# + 5 growth + 4 strategy + 5 foundations.
SKILL_CATEGORIES: dict[str, str] = {
    # Fundraising hybrids (Phase 2 will add native orchestrators)
    "research-vc": "fundraising",
    "prep-week": "fundraising",
    # GTM: customer / ICP
    "gtm-customer-research": "icp",
    "gtm-competitor-profiling": "icp",
    "gtm-competitor-alternatives": "icp",
    "gtm-product-marketing-context": "icp",
    # GTM: copy / outreach
    "gtm-copywriting": "copy",
    "gtm-copy-editing": "copy",
    "gtm-cold-email": "copy",
    "gtm-email-sequence": "copy",
    "gtm-ad-creative": "copy",
    # GTM: conversion / CRO
    "gtm-page-cro": "cro",
    "gtm-form-cro": "cro",
    "gtm-popup-cro": "cro",
    "gtm-onboarding-cro": "cro",
    "gtm-signup-flow-cro": "cro",
    "gtm-paywall-upgrade-cro": "cro",
    # GTM: SEO
    "gtm-seo-audit": "seo",
    "gtm-ai-seo": "seo",
    "gtm-programmatic-seo": "seo",
    "gtm-schema-markup": "seo",
    "gtm-site-architecture": "seo",
    # GTM: distribution
    "gtm-paid-ads": "distribution",
    "gtm-social-content": "distribution",
    "gtm-video": "distribution",
    "gtm-image": "distribution",
    "gtm-community-marketing": "distribution",
    "gtm-directory-submissions": "distribution",
    # GTM: growth / funnel
    "gtm-lead-magnets": "growth",
    "gtm-referral-program": "growth",
    "gtm-free-tool-strategy": "growth",
    "gtm-churn-prevention": "growth",
    "gtm-aso-audit": "growth",
    # GTM: strategy / positioning
    "gtm-pricing-strategy": "strategy",
    "gtm-launch-strategy": "strategy",
    "gtm-content-strategy": "strategy",
    "gtm-marketing-ideas": "strategy",
    # GTM: foundations / ops
    "gtm-analytics-tracking": "foundations",
    "gtm-ab-test-setup": "foundations",
    "gtm-marketing-psychology": "foundations",
    "gtm-sales-enablement": "foundations",
    "gtm-revops": "foundations",
}

VALID_CATEGORIES = sorted(set(SKILL_CATEGORIES.values()))


@dataclass(frozen=True)
class SkillEntry:
    """One skill, lazily loaded — markdown is read on first access."""

    name: str
    path: Path
    description: str
    category: str

    @property
    def markdown(self) -> str:
        """Full markdown body (frontmatter + content) used as system prompt."""
        return self.path.read_text(encoding="utf-8")


def _resolve_skills_root() -> Path:
    """Locate `dormy-skills/reference/`.

    Priority:
      1. `DORMY_SKILLS_PATH` env var (absolute path to `reference/` dir)
      2. <repo_root>/dormy-skills/reference/  — works in local dev + Railway
    """
    env = os.environ.get("DORMY_SKILLS_PATH")
    if env:
        return Path(env)
    # registry.py is at <repo>/dormy/skills/registry.py
    return Path(__file__).parent.parent.parent / "dormy-skills" / "reference"


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Extract YAML frontmatter from a markdown file.

    Returns {} if no frontmatter found (skill will fall back to filename
    as name and a generic description).
    """
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1]) or {}
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError as e:
        logger.warning(f"skill frontmatter parse failed: {e}")
        return {}


class SkillRegistry:
    """Lazy-built registry of all skill markdowns under `reference/`.

    Built once on first access and cached. To force a rebuild after
    adding a new .md, call `registry.reload()`.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root: Path = root or _resolve_skills_root()
        self._entries: dict[str, SkillEntry] | None = None

    @property
    def root(self) -> Path:
        return self._root

    def _build(self) -> dict[str, SkillEntry]:
        out: dict[str, SkillEntry] = {}
        if not self._root.is_dir():
            logger.warning(f"skill registry: {self._root} not found — empty registry")
            return out
        for md in sorted(self._root.glob("*.md")):
            try:
                head = md.read_text(encoding="utf-8")[:4000]
            except OSError as e:
                logger.warning(f"skill registry: failed to read {md.name}: {e}")
                continue
            fm = _parse_frontmatter(head)
            name = fm.get("name") or md.stem
            description = fm.get("description") or f"Skill {name} (no description)"
            # Description in frontmatter is often multi-paragraph — keep first
            # 600 chars for the tool list (LLM uses this to filter), full
            # markdown is what feeds the run_skill system prompt.
            description = str(description).strip()
            if len(description) > 600:
                description = description[:597].rstrip() + "..."
            category = SKILL_CATEGORIES.get(name, "other")
            out[name] = SkillEntry(
                name=name,
                path=md,
                description=description,
                category=category,
            )
        return out

    @property
    def entries(self) -> dict[str, SkillEntry]:
        if self._entries is None:
            self._entries = self._build()
        return self._entries

    def reload(self) -> None:
        self._entries = None

    def get(self, name: str) -> SkillEntry:
        try:
            return self.entries[name]
        except KeyError:
            raise KeyError(
                f"unknown skill '{name}' — known: {sorted(self.entries.keys())[:10]}..."
            ) from None

    def list_all(self) -> list[SkillEntry]:
        return list(self.entries.values())

    def list_by_category(self, category: str) -> list[SkillEntry]:
        return [e for e in self.entries.values() if e.category == category]

    def categories(self) -> list[str]:
        seen = {e.category for e in self.entries.values()}
        return sorted(seen)


# Module-level singleton — import this from MCP / Telegram surfaces.
registry = SkillRegistry()
