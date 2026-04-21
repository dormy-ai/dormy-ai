"""Markdown chunker — splits a document into ~500-token chunks with overlap.

Uses tiktoken (cl100k_base, the embedding tokenizer) so chunks respect the
actual token budget of text-embedding-3-small (8191 max).
"""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken

_ENC = tiktoken.get_encoding("cl100k_base")

DEFAULT_CHUNK_TOKENS = 500
DEFAULT_OVERLAP_TOKENS = 50


@dataclass(slots=True)
class Chunk:
    index: int
    content: str
    token_count: int


def chunk_text(
    text: str,
    *,
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Split `text` into token-bounded overlapping chunks."""
    text = text.strip()
    if not text:
        return []

    tokens = _ENC.encode(text)
    if len(tokens) <= chunk_tokens:
        return [Chunk(index=0, content=text, token_count=len(tokens))]

    chunks: list[Chunk] = []
    step = chunk_tokens - overlap_tokens
    i = 0
    idx = 0
    while i < len(tokens):
        window = tokens[i : i + chunk_tokens]
        content = _ENC.decode(window)
        chunks.append(Chunk(index=idx, content=content, token_count=len(window)))
        idx += 1
        i += step
        if i + overlap_tokens >= len(tokens):
            break

    return chunks
