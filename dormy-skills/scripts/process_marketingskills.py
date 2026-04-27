#!/usr/bin/env python3
"""Generate Dormy artifacts from vendored marketingskills.

Two outputs per upstream skill:

1. **Vault playbook** (Layer 1 — RAG ingest)
   `<vault>/Dormy/GTM/Playbooks/marketingskills-<name>.md`
   Frontmatter declares tags so `dormy knowledge sync` chunks + embeds
   the skill body keyed by sub-category.

2. **Dormy-adapted Claude Code skill** (Layer 2 — `/dormy gtm-<name>`)
   `dormy-skills/reference/gtm-<name>.md`
   Dormy-style frontmatter + the upstream body + a "Dormy MCP integration"
   appendix that suggests `mcp_dormy_memory_recall(tags=[...])` calls.

Run idempotently — re-running overwrites generated files. Quarterly
upstream sync: `bash scripts/check-upstream-marketingskills.sh` to see
what's new, `git subtree pull` if relevant, then re-run this script.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 8-category map. Sub-tag goes into the GTM RAG keyspace + skill's
# memory_recall hint. Categories chosen so super-founders intuit them.
CATEGORY_MAP: dict[str, str] = {
    # Customer / ICP
    "customer-research": "icp",
    "competitor-profiling": "icp",
    "competitor-alternatives": "icp",
    "product-marketing-context": "icp",
    # Copy / Outreach
    "copywriting": "copy",
    "copy-editing": "copy",
    "cold-email": "copy",
    "email-sequence": "copy",
    "ad-creative": "copy",
    # Conversion / CRO
    "page-cro": "cro",
    "form-cro": "cro",
    "popup-cro": "cro",
    "onboarding-cro": "cro",
    "signup-flow-cro": "cro",
    "paywall-upgrade-cro": "cro",
    # SEO
    "seo-audit": "seo",
    "ai-seo": "seo",
    "programmatic-seo": "seo",
    "schema-markup": "seo",
    "site-architecture": "seo",
    # Distribution
    "paid-ads": "distribution",
    "social-content": "distribution",
    "video": "distribution",
    "image": "distribution",
    "community-marketing": "distribution",
    "directory-submissions": "distribution",
    # Growth / Funnel
    "lead-magnets": "growth",
    "referral-program": "growth",
    "free-tool-strategy": "growth",
    "churn-prevention": "growth",
    "aso-audit": "growth",
    # Strategy / Positioning
    "pricing-strategy": "strategy",
    "launch-strategy": "strategy",
    "content-strategy": "strategy",
    "marketing-ideas": "strategy",
    # Foundations / Ops
    "analytics-tracking": "foundations",
    "ab-test-setup": "foundations",
    "marketing-psychology": "foundations",
    "sales-enablement": "foundations",
    "revops": "foundations",
}

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCES_DIR = REPO_ROOT / "dormy-skills" / "sources" / "marketingskills" / "skills"
REFERENCE_DIR = REPO_ROOT / "dormy-skills" / "reference"

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def parse_skill_md(path: Path) -> tuple[dict[str, str], str]:
    """Return (frontmatter_dict, body) for a SKILL.md. Frontmatter parsed loosely
    — we only need `name` and `description`, and we want to preserve the body."""
    text = path.read_text()
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm_block, body = m.group(1), m.group(2).lstrip("\n")
    fm: dict[str, str] = {}
    current_key = None
    current_lines: list[str] = []
    for line in fm_block.splitlines():
        # top-level key: value
        kv = re.match(r"^([a-zA-Z_][a-zA-Z0-9_-]*):\s*(.*)$", line)
        if kv and not line.startswith(" "):
            if current_key is not None:
                fm[current_key] = "\n".join(current_lines).strip()
            current_key = kv.group(1)
            current_lines = [kv.group(2)] if kv.group(2) else []
        else:
            current_lines.append(line)
    if current_key is not None:
        fm[current_key] = "\n".join(current_lines).strip()
    return fm, body


def title_from_name(name: str) -> str:
    """`cold-email` → `Cold Email`."""
    return " ".join(w.capitalize() for w in name.split("-"))


def vault_markdown(name: str, category: str, fm: dict[str, str], body: str) -> str:
    """Produce the vault playbook file content for RAG ingest."""
    title = title_from_name(name)
    description = fm.get("description", "").replace("\n", " ").strip()
    return f"""---
title: {title}
tags: [marketingskills, {category}, playbook]
source: marketingskills
upstream_skill: {name}
author: Corey Haines
license: MIT
---

# {title} (marketingskills)

> Ingested from [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills)
> by Corey Haines. License: MIT. Verbatim copy of the upstream `SKILL.md`
> body — Dormy uses this as RAG context for any GTM question that maps to
> this skill's domain.

**When to apply this framework:** {description}

---

{body}
"""


def adapted_skill_markdown(name: str, category: str, fm: dict[str, str], body: str) -> str:
    """Produce the Dormy-flavored Claude Code skill file (reference/gtm-<name>.md)."""
    title = title_from_name(name)
    description = fm.get("description", "").replace("\n", " ").strip()
    return f"""---
name: gtm-{name}
description: |
  {description}

  Dormy adaptation: when invoked through Claude Code with the Dormy MCP
  configured, this skill calls `mcp_dormy_memory_recall(tags=['gtm', '{category}'])`
  for cross-skill context plus `mcp_dormy_memory_recall(tags=['founder-profile'])`
  for founder positioning before drafting. Falls back to fully client-side
  workflow when MCP is absent.
license: MIT (derivative of coreyhaines31/marketingskills by Corey Haines)
---

# {title}

> Adapted from upstream `marketingskills/{name}` (MIT). Source preserved
> verbatim under `dormy-skills/sources/marketingskills/skills/{name}/`.

## Paradigm

Hybrid — fully client-side by default; richer if Dormy MCP is configured.

## Dormy MCP integration (if configured)

Before applying the framework below, optionally:

1. `mcp_dormy_memory_recall(query="<user's specific prompt>", tags=['gtm', '{category}'])`
   — pulls the founder's curated GTM playbook chunks (this skill + cross-references).
2. `mcp_dormy_memory_recall(query="founder profile", tags=['founder-profile'])`
   — pulls positioning, sector, current stage so the output is personalized
   instead of generic.
3. The fire-and-forget memory hook on the MCP side will auto-extract any
   strategic decisions from the user's reply (no explicit call needed).

If MCP is not configured, skip and run client-side.

---

{body}

---

## Output handoff

When done, suggest:
- "Want me to save this to your founder profile?" (only if it changes positioning / ICP / pricing — Dormy will store via the next MCP call)
- "Want a Telegram-friendly short version for sharing in your team chat?" (rewrite to ~200 chars)
"""


def write_with_dirs(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vault",
        type=Path,
        default=None,
        help="Obsidian vault root (the dir containing `Dormy/`). "
        "Skip vault writes if not provided (Layer 2 only).",
    )
    parser.add_argument(
        "--skip-reference",
        action="store_true",
        help="Skip Layer 2 (dormy-skills/reference/gtm-*.md) generation.",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        help="Process only these skill names (debug). Defaults to all 40.",
    )
    args = parser.parse_args()

    if not SOURCES_DIR.is_dir():
        print(f"❌ Sources dir not found: {SOURCES_DIR}", file=sys.stderr)
        return 1

    skill_dirs = sorted(p for p in SOURCES_DIR.iterdir() if p.is_dir())
    if args.only:
        skill_dirs = [p for p in skill_dirs if p.name in args.only]

    n_vault = 0
    n_ref = 0
    skipped: list[str] = []

    vault_target = None
    if args.vault is not None:
        # `--vault` points at the dir that already contains GTM/, Fundraising/,
        # etc. (matches DORMY_OBSIDIAN_VAULT_PATH convention from .env).
        vault_target = args.vault / "GTM" / "Playbooks"
        vault_target.mkdir(parents=True, exist_ok=True)

    for skill_dir in skill_dirs:
        name = skill_dir.name
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            skipped.append(f"{name}: no SKILL.md")
            continue

        category = CATEGORY_MAP.get(name)
        if category is None:
            skipped.append(f"{name}: no category mapping")
            continue

        fm, body = parse_skill_md(skill_md)

        if vault_target is not None:
            vault_path = vault_target / f"marketingskills-{name}.md"
            write_with_dirs(vault_path, vault_markdown(name, category, fm, body))
            n_vault += 1

        if not args.skip_reference:
            ref_path = REFERENCE_DIR / f"gtm-{name}.md"
            write_with_dirs(ref_path, adapted_skill_markdown(name, category, fm, body))
            n_ref += 1

    print(f"✅ Wrote {n_vault} vault playbooks + {n_ref} reference skills")
    if skipped:
        print("\nSkipped:")
        for s in skipped:
            print(f"  - {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
