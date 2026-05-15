# EfficientAI Fumadocs

New docs stack for EfficientAI using Fumadocs + Next.js static export.

## Development

```bash
npm run dev
```

Open `http://localhost:3000/docs/intro`.

## Content

- Docs content: `content/docs`
- Navigation: `content/docs/meta.json` and section-level `meta.json`
- Contributor metadata:
  - Manual owner overrides: `content/feature-owners.json`
  - Generated contributor data: `content/feature-contributors.json`

## Checks

```bash
npm run contributors:generate
npm run ci:check
```

`ci:check` runs contributor consistency, docs validation, link checks, type checks, and production build.

## Deployment

Deployment is handled by `.github/workflows/deploy-docs.yml` and publishes static output from `docs-fumadocs/out`.

Rollback instructions are documented in `CUTOVER.md`.
