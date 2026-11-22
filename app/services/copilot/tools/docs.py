"""Search the EAI product docs (``docs_index.json``, built by scripts/build_copilot_docs_index.py).

BM25 over heading-sized sections, built once per process: no embedding calls,
no per-org setup, deterministic results, microseconds per query.
"""

from __future__ import annotations

import json
import math
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.copilot.registry import CopilotTool, ToolContext, register

INDEX_PATH = Path(__file__).resolve().parents[1] / "docs_index.json"
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be by can do does for from how i in is it of on or that the this to "
    "what when where which who why with you your my we our".split()
)
K1, B = 1.4, 0.75
TITLE_BOOST = 2  # title/heading words count this many extra times


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


class _Index:
    def __init__(self, entries: list[dict]):
        self.entries = entries
        self.docs: list[Counter] = []
        df: Counter = Counter()
        for e in entries:
            heading = f"{e['title']} {e['section']}"
            terms = Counter(_tokens(e["text"]))
            for _ in range(TITLE_BOOST):
                terms.update(_tokens(heading))
            self.docs.append(terms)
            df.update(terms.keys())
        n = max(1, len(entries))
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_len = sum(self.lengths) / n if self.lengths else 1.0
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, limit: int) -> list[tuple[float, dict]]:
        terms = set(_tokens(query))
        scored = []
        for doc, length, entry in zip(self.docs, self.lengths, self.entries):
            score = 0.0
            for term in terms:
                tf = doc.get(term)
                if tf:
                    score += self.idf[term] * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / self.avg_len))
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda s: s[0], reverse=True)
        return scored[:limit]


_index: Optional[_Index] = None
_lock = threading.Lock()


def get_index() -> _Index:
    global _index
    with _lock:
        if _index is None:
            try:
                entries = json.loads(INDEX_PATH.read_text(encoding="utf-8"))["entries"]
            except (OSError, ValueError, KeyError):
                entries = []
            _index = _Index(entries)
        return _index


class DocsArgs(BaseModel):
    query: str = Field(..., min_length=2, max_length=300, description="What to look up, in plain words.")
    limit: int = Field(4, ge=1, le=8)


def search_docs(ctx: ToolContext, db: Session, args: DocsArgs) -> dict:
    hits = get_index().search(args.query, args.limit)
    return {
        "results": [
            {"title": e["title"], "section": e["section"], "url": e["url"], "text": e["text"][:1200]}
            for _, e in hits
        ],
        "note": "Answer from these excerpts and cite the url of each one you use. "
        "If none answers the question, say the docs don't cover it.",
    }


register(CopilotTool(
    name="search_docs",
    description=(
        "Search the EfficientAI product documentation (how features work, setup guides, "
        "integrations, API reference). Use for 'how do I…' questions about the platform."
    ),
    args_model=DocsArgs,
    handler=search_docs,
    needs_db=False,
))
