# Publishing Fumadocs archive to Confluence (ETD)

Use this when Atlassian MCP is slow or unavailable. Source files: `monitoring/call-traces/*.md`.

## Target structure

```
ETD (space)
└── Fumadocs archive                    [folder]
    └── Monitoring / Call Traces        [folder or parent page]
        ├── Call Traces — overview      ← 01-overview.md
        ├── Latency metrics             ← 02-latency-metrics.md
        ├── Architecture & scaling      ← 03-architecture-and-scaling.md
        └── Pipecat & OTLP integration  ← 04-pipecat-otlp-integration.md
```

## Manual steps

1. In [ETD space](https://efficientai.atlassian.net/wiki/spaces/ETD), create **folder** **Fumadocs archive** (suggested parent: [Voice Call Traces index](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/69959682) or space root).
2. Create landing page **Fumadocs archive (index)** from `00-fumadocs-archive-index.md`.
3. Under it, create **folder** **Monitoring → Call Traces** (optional) or four sibling pages.
4. For each child page: **Create → Page**, paste from the matching `.md` file. Confluence accepts Markdown on paste in many editors; or use **Insert markup** / convert tables if needed.
5. Add a short blurb on the parent folder:

   > Staging copies of public docs (`docs-fumadocs`) until the main docs site is updated. Canonical git copies: `docs/confluence-fumadocs-archive/` on branch `otel-traces`.

## MCP (when stable)

```json
{
  "cloudId": "https://efficientai.atlassian.net",
  "contentType": "folder",
  "title": "Fumadocs archive",
  "parent": { "spaceId": "950276" }
}
```

Then create child `page` entries with `parentContentId` set to the folder id and `body: { "format": "markdown", "value": "<file contents>" }`.

Record created page IDs below after publish:

| Page | Confluence ID | URL |
| --- | --- | --- |
| Fumadocs archive (index) | 76709889 | https://efficientai.atlassian.net/wiki/spaces/ETD/pages/76709889 |
| Call Traces — overview | 76775425 | https://efficientai.atlassian.net/wiki/spaces/ETD/pages/76775425 |
| Latency metrics | 76840961 | https://efficientai.atlassian.net/wiki/spaces/ETD/pages/76840961 |
| Architecture & scaling | 76873729 | https://efficientai.atlassian.net/wiki/spaces/ETD/pages/76873729 |
| Pipecat & OTLP integration (includes **agent lab quickstart**) | 76808193 | https://efficientai.atlassian.net/wiki/spaces/ETD/pages/76808193 |
| ~~Pipecat agent lab~~ (redirect only — do not maintain) | 78774273 | https://efficientai.atlassian.net/wiki/spaces/ETD/pages/78774273 |
| Scaling TDD v2.0 (internal) | 76349452 | https://efficientai.atlassian.net/wiki/spaces/ETD/pages/76349452 |
| Old scaling URL (redirect) | 72417282 | https://efficientai.atlassian.net/wiki/spaces/ETD/pages/72417282 |
