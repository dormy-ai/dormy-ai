"""fetch_page — pull visible text + OG metadata from any URL.

Telegram bot can't see the link previews its client renders; without this
tool, bot LLM reasons from the bare URL string and either hallucinates
or asks the user to paste content. This tool gives any surface a way to
read the page so the downstream playbook (gtm-page-cro, gtm-seo-audit,
gtm-competitor-profiling, etc.) actually has substance to critique.

Single source of truth: `run_fetch_page()` is imported by both the MCP
register wrapper here and `dormy.telegram.tools`. Same pattern as
`run_web_search` / `run_recent_funding` / `run_skill`.

Intentionally simple — no Playwright / JS rendering. Static HTML only.
For SPA-heavy sites where text lives in JS bundles we degrade to
"title + description" + whatever cleaned text is in the response.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import httpx
from loguru import logger
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


FETCH_TIMEOUT = httpx.Timeout(15.0)
DEFAULT_MAX_CHARS = 12000  # ~3K tokens — fits in a single playbook system prompt
USER_AGENT = "Dormy-Fetch/1.0 (+https://heydormy.ai)"


class PageFetchResult(BaseModel):
    url: str
    final_url: str | None = Field(
        default=None,
        description="Resolved URL after redirects (None if same as input)",
    )
    title: str | None = None
    description: str | None = Field(
        default=None,
        description="<meta name=description> or og:description",
    )
    headings: list[str] = Field(
        default_factory=list,
        description="H1 + H2 text in document order (deduped, stripped)",
    )
    text: str = Field(description="Cleaned visible text, capped to max_chars")
    chars: int
    data_source: str = Field(description="http | error")
    note: str


def _error_result(url: str, message: str) -> PageFetchResult:
    return PageFetchResult(
        url=url,
        final_url=None,
        title=None,
        description=None,
        headings=[],
        text="",
        chars=0,
        data_source="error",
        note=message,
    )


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_META_DESC_RE = re.compile(
    r'<meta\s+[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']',
    re.I,
)
_OG_DESC_RE = re.compile(
    r'<meta\s+[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']',
    re.I,
)
_HEADING_RE = re.compile(r"<h[12][^>]*>(.*?)</h[12]>", re.S | re.I)
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.S | re.I)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_tags(s: str) -> str:
    """Remove HTML tags, collapse whitespace."""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", s)).strip()


def _extract(html: str) -> tuple[str | None, str | None, list[str], str]:
    title_m = _TITLE_RE.search(html)
    title = _strip_tags(title_m.group(1)) if title_m else None

    desc_m = _META_DESC_RE.search(html) or _OG_DESC_RE.search(html)
    description = desc_m.group(1).strip() if desc_m else None

    headings: list[str] = []
    seen: set[str] = set()
    for m in _HEADING_RE.finditer(html):
        h = _strip_tags(m.group(1))
        if h and h not in seen and len(h) < 200:
            headings.append(h)
            seen.add(h)
        if len(headings) >= 12:
            break

    cleaned = _SCRIPT_RE.sub("", html)
    cleaned = _STYLE_RE.sub("", cleaned)
    cleaned = _strip_tags(cleaned)
    return title, description, headings, cleaned


async def run_fetch_page(
    url: str,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> PageFetchResult:
    """Fetch a URL, extract title/description/headings/text. Returns a
    structured result; never raises — errors come back as data_source='error'.
    """
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return _error_result(url, "url must start with http:// or https://")

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=FETCH_TIMEOUT,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh;q=0.8",
            },
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
            final = str(resp.url)
    except httpx.HTTPStatusError as e:
        logger.warning(f"fetch_page HTTP {e.response.status_code}: {url}")
        return _error_result(url, f"HTTP {e.response.status_code} from {url}")
    except Exception as e:
        logger.warning(f"fetch_page failed: {url} — {e}")
        return _error_result(url, f"fetch failed: {e}")

    title, description, headings, cleaned = _extract(html)
    capped = cleaned[:max_chars]
    return PageFetchResult(
        url=url,
        final_url=final if final != url else None,
        title=title,
        description=description,
        headings=headings,
        text=capped,
        chars=len(capped),
        data_source="http",
        note=(
            f"Fetched {url} — title={'yes' if title else 'no'}, "
            f"meta_desc={'yes' if description else 'no'}, "
            f"headings={len(headings)}, body_chars={len(capped)}"
        ),
    )


def register(mcp: "FastMCP") -> None:
    @mcp.tool(
        description=(
            "Fetch a public web page and extract its visible content "
            "(title + meta description + h1/h2 headings + cleaned body "
            "text, capped at ~12K chars). Use BEFORE run_skill for any "
            "playbook that critiques a URL: gtm-page-cro, gtm-seo-audit, "
            "gtm-competitor-profiling, gtm-competitor-alternatives, "
            "gtm-form-cro, etc. Without this, the playbook has nothing "
            "to analyze. Static HTML only — no JS rendering."
        ),
    )
    async def fetch_page(
        url: str = Field(description="Full URL with http:// or https:// scheme"),
        max_chars: int = Field(
            default=DEFAULT_MAX_CHARS,
            ge=500,
            le=40000,
            description="Cap on body text length (defaults to ~12K chars / ~3K tokens)",
        ),
    ) -> PageFetchResult:
        return await run_fetch_page(url=url, max_chars=max_chars)
