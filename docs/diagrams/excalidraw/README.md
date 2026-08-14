# Call Import Architecture — Excalidraw Diagrams

All call-import architecture diagrams live in **one file** for easy tracking and editing.

## Single combined file

| File | Description |
|------|-------------|
| [`call-import-architecture.excalidraw`](call-import-architecture.excalidraw) | All 6 diagrams stacked vertically with section headers (01–06) |

### Sections inside the file

| # | Section | Contents |
|---|---------|----------|
| 01 | Platform Architecture | K8s cluster: API, workers, Redis, catalog + 4 shards, external services |
| 02 | Postgres ↔ Redis ↔ Workers | 7-step coordination loop |
| 03 | Call Import Pipeline | End-to-end stages and import vs eval slot types |
| 04 | Database Sharding | Catalog vs data shards, routing formula, pool layout |
| 05 | Fair Dispatch & Inflight Limits | Workspace RR, limit hierarchy, dual 10k numbers |
| 06 | Scaling Roadmap | Now (no PgBouncer) vs future scaling phases |

Scroll down in Excalidraw to move between sections. Each section has a blue header bar (01–06).

## How to open & edit

### VS Code / Cursor (recommended)

1. Install the [Excalidraw extension](https://marketplace.visualstudio.com/items?itemName=pomdtr.excalidraw-editor)
2. Open `call-import-architecture.excalidraw`
3. Edit visually; save commits the JSON back to the repo

### Excalidraw.com

1. Go to [excalidraw.com](https://excalidraw.com)
2. **Open → Load from file** and select `call-import-architecture.excalidraw`

### Regenerate from script

After changing layout code:

```bash
python3 scripts/generate_call_import_excalidraw_diagrams.py
```

Source: `scripts/excalidraw_builder.py` + `scripts/generate_call_import_excalidraw_diagrams.py`

## Embed in Confluence

1. Open the combined file in Excalidraw
2. Zoom to the section you need, or export the full canvas
3. **Export → PNG** or **SVG**
4. In Confluence page editor: insert image at the relevant section

## Related docs

- **Operator handbook (Confluence):** [Call Import Scaling — Operator Handbook (2 pages)](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/59932681)
- **Full scaling guide (Confluence):** [Call Import Architecture & Scaling Guide](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/59899905)
- PowerPoint: `docs/presentations/EfficientAI_Call_Import_Architecture_and_Scaling.pptx`
- Load test: `docs/operations/call-import-sharding-load-test.md`
