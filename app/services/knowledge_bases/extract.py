"""Extract plain text from knowledge base source files."""

from __future__ import annotations

import io
from typing import List, Optional, Tuple


def extract_text_from_bytes(file_bytes: bytes, *, extension: str) -> List[Tuple[Optional[int], str]]:
    ext = extension.lower().lstrip(".")
    if ext in ("txt", "md"):
        text = file_bytes.decode("utf-8", errors="replace")
        return [(None, text)]
    if ext == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        pages: List[Tuple[Optional[int], str]] = []
        for i, page in enumerate(reader.pages):
            pages.append((i + 1, page.extract_text() or ""))
        return pages
    if ext == "docx":
        import docx

        document = docx.Document(io.BytesIO(file_bytes))
        paragraphs = "\n".join(p.text for p in document.paragraphs if p.text)
        return [(None, paragraphs)]
    raise ValueError(f"Unsupported extension: {extension}")
