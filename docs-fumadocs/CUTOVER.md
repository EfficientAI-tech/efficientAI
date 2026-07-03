# Docs Cutover and Stabilization

This runbook tracks the Fumadocs rollout strategy.

## Cutover steps

1. Ensure `docs-fumadocs` checks are green in the `Docs` workflow `build` job.
2. Confirm CloudFront has the viewer-request function from [`infra/cloudfront-viewer-request.js`](infra/cloudfront-viewer-request.js) attached and no 404→`/index.html` SPA fallback.
3. Trigger the `Docs` workflow `deploy` job (or push to `main` with docs changes).
4. Verify production routes (direct URL and refresh — not just sidebar clicks):
   - `https://docs.efficientai.cloud/docs/intro/`
   - `https://docs.efficientai.cloud/docs/getting-started/integrations/`
   - `https://docs.efficientai.cloud/docs/getting-started/installation/`
   - `https://docs.efficientai.cloud/docs/products/agents/`
   - `https://docs.efficientai.cloud/docs/monitoring/calls/`
   - `https://docs.efficientai.cloud/docs/reference/configuration/`
5. Verify contributor sections render on all feature pages.
6. Record cutover timestamp in the release notes.

## Rollback

If production docs regress, redeploy the last known-good commit that built and exported `docs-fumadocs/out`.

## Stabilization checklist

- Track search failures and broken-link reports.
- Confirm no unresolved internal links from `npm run check:links`.
- Confirm page refresh stays on the same doc page (CloudFront URI rewrite working).
- Confirm bogus URLs (e.g. `/docs/does-not-exist/`) show 404, not intro.
