# EfficientAI Fumadocs

New docs stack for EfficientAI using Fumadocs + Next.js static export.

## Development

```bash
npm run dev
```

Open `http://localhost:3000/docs/intro/`.

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

`ci:check` runs docs validation, link checks, type checks, production build, and static route verification.

## Deployment

Deployment is handled by `.github/workflows/docs.yml` (the `deploy` job) and publishes static output from `docs-fumadocs/out` to S3/CloudFront on pushes to `main` (or via manual workflow dispatch).

Production site: `https://docs.efficientai.cloud`

The `build` job runs the same checks on pull requests. Only public docs content under `content/docs/` is included — there is no separate enterprise docs section or password gate.

### CloudFront routing (required)

Next.js static export with `trailingSlash: true` writes pages as `out/docs/<slug>/index.html`. S3 REST origins do not resolve directory URLs automatically. Without CloudFront URI rewriting, direct URLs and page refreshes fail and may fall back to `/index.html`, which redirects to `/docs/intro/`.

**Required AWS configuration:**

1. Create a CloudFront Function from [`infra/cloudfront-viewer-request.js`](infra/cloudfront-viewer-request.js) (e.g. name `docs-static-uri-rewrite`) and publish it.
2. Attach it to the docs distribution: **Behaviors → Default (\*) → Function associations → Viewer request**.
3. **Remove** any Custom Error Response that maps **404** or **403** → `/index.html` with HTTP **200** (this causes failed doc routes to redirect to intro).
4. Optionally map 404 → `/404.html` with 404 status after deploy includes `out/404.html`.

**Verify after deploy** (direct URL / refresh in incognito):

```
https://docs.efficientai.cloud/docs/intro/
https://docs.efficientai.cloud/docs/getting-started/integrations/
https://docs.efficientai.cloud/docs/products/agents/
https://docs.efficientai.cloud/docs/monitoring/calls/
https://docs.efficientai.cloud/docs/reference/configuration/
```

Set `NEXT_PUBLIC_DOCS_BASE_URL=https://docs.efficientai.cloud` in the deploy environment if metadata canonical URLs should match production.
