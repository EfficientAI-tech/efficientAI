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
- Contributor metadata (optional, static):
  - Manual owner overrides: `content/feature-owners.json`
  - Contributor data: `content/feature-contributors.json`

## Checks

```bash
npm run ci:check
```

`ci:check` runs docs validation, link checks, type checks, and production build.

## Deployment

Deployment is handled by `.github/workflows/docs.yml` (the `deploy` job) and publishes static output from `docs-fumadocs/out` to S3/CloudFront on pushes to `main` (or via manual workflow dispatch).

The `build` job runs the same checks on pull requests. Only public docs content under `content/docs/` is included — there is no separate enterprise docs section or password gate.
