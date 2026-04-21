"""Obsidian-flavored Markdown helpers.

Parses YAML frontmatter + body from a .md file. Keeps no global state; safe
for concurrent use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


_FRONT_DELIM = "---"


def parse_markdown_file(path: Path) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body_text) for a .md file.

    Frontmatter is an optional YAML block delimited by `---` at the top.
    Files without frontmatter return an empty dict plus the full body.
    """
    text = path.read_text(encoding="utf-8")
    return parse_markdown(text)


def parse_markdown(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown string into (frontmatter, body)."""
    if not text.startswith(_FRONT_DELIM):
        return {}, text

    # Find the closing delimiter on its own line.
    # Skip the opening "---\n" (4 chars).
    after_open = text[len(_FRONT_DELIM):]
    if not after_open.startswith("\n"):
        return {}, text

    end_idx = after_open.find(f"\n{_FRONT_DELIM}")
    if end_idx == -1:
        return {}, text

    raw_yaml = after_open[1:end_idx]          # strip the leading newline
    rest_start = end_idx + 1 + len(_FRONT_DELIM)
    body = after_open[rest_start:].lstrip("\n")

    try:
        front = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError:
        front = {}
    if not isinstance(front, dict):
        front = {}
    return front, body
