"""Text chunking for knowledge base ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List, Optional


@dataclass(frozen=True)
class TextChunk:
    text: str
    chunk_index: int
    page_number: Optional[int] = None


def chunk_text_pages(
    pages: List[tuple[Optional[int], str]],
    *,
    max_chars: int = 3200,
    overlap_chars: int = 400,
) -> List[TextChunk]:
    """Split page text into overlapping chunks (~800 tokens at 4 chars/token)."""
    chunks: List[TextChunk] = []
    idx = 0
    for page_number, page_text in pages:
        normalized = (page_text or "").strip()
        if not normalized:
            continue
        start = 0
        length = len(normalized)
        while start < length:
            end = min(start + max_chars, length)
            piece = normalized[start:end].strip()
            if piece:
                chunks.append(TextChunk(text=piece, chunk_index=idx, page_number=page_number))
                idx += 1
            if end >= length:
                break
            start = max(0, end - overlap_chars)
    return chunks


def chunk_plain_text(text: str, **kwargs) -> List[TextChunk]:
    return chunk_text_pages([(None, text)], **kwargs)
