#!/usr/bin/env bash
# Check what's new in coreyhaines31/marketingskills since our last vendor sync.
# Run quarterly. Decide manually whether to pull.

set -euo pipefail

UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-marketingskills-upstream}"
PREFIX="dormy-skills/sources/marketingskills"

# Re-add the remote if missing (devs cloning fresh won't have it)
if ! git remote get-url "$UPSTREAM_REMOTE" >/dev/null 2>&1; then
  echo "→ Adding remote $UPSTREAM_REMOTE"
  git remote add "$UPSTREAM_REMOTE" \
    https://github.com/coreyhaines31/marketingskills.git
fi

echo "→ Fetching upstream"
git fetch --quiet "$UPSTREAM_REMOTE" main

# Pull the SHA we last vendored from UPSTREAM.md (matches "**Vendored at commit**: `<sha>`")
LAST_SHA=$(grep -E "Vendored at commit" dormy-skills/sources/UPSTREAM.md \
  | head -1 \
  | sed -E "s/.*\`([a-f0-9]+)\`.*/\1/")

if [ -z "$LAST_SHA" ]; then
  echo "❌ Could not parse last vendored SHA from UPSTREAM.md"
  exit 1
fi

UPSTREAM_HEAD=$(git rev-parse "$UPSTREAM_REMOTE/main")

if [ "$LAST_SHA" = "$UPSTREAM_HEAD" ]; then
  echo "✅ Up to date — last vendored = upstream HEAD ($LAST_SHA)"
  exit 0
fi

echo
echo "📋 New upstream commits since last sync ($LAST_SHA → $UPSTREAM_HEAD):"
echo
git log --oneline --no-decorate "$LAST_SHA..$UPSTREAM_HEAD"

echo
echo "📂 Files changed:"
git diff --stat "$LAST_SHA..$UPSTREAM_HEAD" -- "skills/" || true

echo
echo "To pull these in:"
echo "  git subtree pull --prefix=$PREFIX $UPSTREAM_REMOTE main --squash"
echo "  # then bump SHA + date in dormy-skills/sources/UPSTREAM.md"
