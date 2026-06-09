# Docs Cutover and Stabilization

This runbook tracks the Fumadocs rollout and rollback strategy.

## Cutover steps

1. Ensure `docs-fumadocs` checks are green in the `Docs` workflow `build` job.
2. Trigger the `Docs` workflow `deploy` job (or push to `main` with docs changes).
3. Verify production routes:
   - `/docs/intro`
   - `/docs/getting-started/installation`
   - `/docs/products/agents`
   - `/docs/monitoring/calls`
4. Verify contributor sections render on all feature pages.
5. Record cutover timestamp in the release notes.

## Rollback

If production docs regress, redeploy the last known-good commit that built and exported `docs-fumadocs/out`.

## Stabilization checklist

- Check CloudFront/S3 404 metrics for docs paths for at least one release window.
- Track search failures and broken-link reports.
- Confirm no unresolved internal links from `npm run check:links`.
- Regenerate contributor metadata weekly or when major docs edits land:
  - `npm run contributors:generate`
