"""Build the copilot's docs search index from docs-fumadocs/content.

The backend image doesn't ship the docs site, so the index is generated here
and committed as app/services/copilot/docs_index.json. Re-run after editing
the docs:

    python scripts/build_copilot_docs_index.py

Guides are split into sections by heading. API-reference pages contribute only
their title and description (the endpoint bodies are long and repetitive).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "docs-fumadocs" / "content" / "docs"
OUT = ROOT / "app" / "services" / "copilot" / "docs_index.json"
BASE_URL = "https://docs.efficientai.cloud/docs"
SKIP_DIRS = {"changelog", "blog"}
MAX_SECTION_CHARS = 1_800

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)
_IMPORT = re.compile(r"^(import|export)\s.*$", re.M)
_JSX_BLOCK = re.compile(r"<([A-Z][A-Za-z0-9]*)[^>]*/>", re.S)
_JSX_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9.]*(\s[^<>]*)?/?>", re.S)
_CODE_FENCE = re.compile(r"```.*?```", re.S)
_HEADING = re.compile(r"^(#{1,3})\s+(.*)$", re.M)


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip("'\"")
    return meta, text[match.end():]


def _url(path: Path) -> str:
    parts = [p for p in path.relative_to(CONTENT).with_suffix("").parts if not p.startswith("(")]
    if parts and parts[-1] == "index":
        parts = parts[:-1]
    return BASE_URL + ("/" + "/".join(parts) if parts else "")


def _clean(body: str) -> str:
    body = _IMPORT.sub("", body)
    body = _CODE_FENCE.sub(lambda m: m.group(0) if len(m.group(0)) < 400 else "", body)
    body = _JSX_BLOCK.sub("", body)
    body = _JSX_TAG.sub("", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def _sections(title: str, body: str) -> list[tuple[str, str]]:
    matches = list(_HEADING.finditer(body))
    if not matches:
        return [(title, body)]
    out = []
    if matches[0].start() > 0:
        out.append((title, body[: matches[0].start()]))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        heading = match.group(2).strip()
        out.append((heading if heading != title else title, body[match.end():end]))
    return out


def build() -> list[dict]:
    entries: list[dict] = []
    for path in sorted(CONTENT.rglob("*.mdx")):
        rel = path.relative_to(CONTENT)
        if rel.parts and rel.parts[0] in SKIP_DIRS:
            continue
        meta, body = _frontmatter(path.read_text(encoding="utf-8"))
        title = meta.get("title") or path.stem.replace("-", " ").title()
        url = _url(path)
        description = meta.get("description", "")
        if rel.parts and rel.parts[0] == "api-reference":
            entries.append({"title": title, "section": "API reference", "url": url, "text": description})
            continue
        for heading, text in _sections(title, _clean(body)):
            text = text.strip()
            if len(text) < 40:
                continue
            anchor = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
            entries.append({
                "title": title,
                "section": heading,
                "url": url + (f"#{anchor}" if heading != title else ""),
                "text": (description + "\n" if heading == title and description else "") + text[:MAX_SECTION_CHARS],
            })
    return entries


def main() -> int:
    if not CONTENT.is_dir():
        print(f"docs not found at {CONTENT}", file=sys.stderr)
        return 1
    entries = build()
    OUT.write_text(json.dumps({"version": 1, "entries": entries}, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {len(entries)} sections to {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
