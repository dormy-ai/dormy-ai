# Vendored upstream sources

This directory holds **read-only mirrors** of third-party Claude skill packs
that Dormy borrows from. Files inside `marketingskills/` are vendored verbatim
via `git subtree` — never edit them in place. Dormy-flavored derivative
skills live in `../reference/gtm-*.md` instead.

## marketingskills

- **Source**: https://github.com/coreyhaines31/marketingskills
- **Author**: Corey Haines (@coreyhaines31)
- **License**: MIT (preserved verbatim in `marketingskills/LICENSE`)
- **Vendored at commit**: `1bcff9fc79c64fd7886c3c7aa583f4bd63916ff2`
- **Vendored on**: 2026-04-27
- **Last reviewed**: 2026-04-27 (initial vendor)
- **40 skills covered**: see `marketingskills/skills/`

## Sync policy

We do **not** auto-pull from upstream. Quarterly manual review is the policy:

```bash
# Check what's new since last sync
bash scripts/check-upstream-marketingskills.sh

# If anything looks worth picking up, do a subtree pull:
git subtree pull --prefix=dormy-skills/sources/marketingskills \
  marketingskills-upstream main --squash
# Then update this file's "Vendored at commit" + "Last reviewed" lines.

# If you adopted a specific upstream change into a derivative skill,
# note it in the relevant `../reference/gtm-*.md` file's changelog.
```

Why no auto-sync: our derivatives in `../reference/gtm-*.md` have
diverged on purpose (Dormy MCP integration, voice). Auto-pull would
risk overwriting the original markdown that our generator script reads
from on next regeneration. Manual review preserves intent.

## Attribution

Per the upstream MIT license, attribution lives in:
- `marketingskills/LICENSE` (verbatim)
- `dormy-skills/SKILL.md` (top-of-file credit line)
- Each derivative `../reference/gtm-*.md` (frontmatter `license` field)
