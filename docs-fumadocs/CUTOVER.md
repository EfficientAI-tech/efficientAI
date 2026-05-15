# Docs Cutover and Stabilization

This runbook tracks the Fumadocs rollout and the one-window rollback strategy.

## Cutover steps

1. Ensure `docs-fumadocs` checks are green in `Docs Quality`.
2. Trigger `Deploy Docs to S3` with `deploy_target=fumadocs` (or push to `main` with docs changes).
3. Verify production routes:
   - `/docs/intro`
   - `/docs/getting-started/installation`
   - `/docs/products/agents`
   - `/docs/monitoring/calls`
4. Verify contributor sections render on all feature pages.
5. Record cutover timestamp in the release notes.

## Rollback (one release window)

If production docs regress, trigger `Deploy Docs to S3` with:

- `deploy_target=legacy`

This deploys the previous Docusaurus site from `EfficientAI-Docs/build`.

## Stabilization checklist

- Check CloudFront/S3 404 metrics for docs paths for at least one release window.
- Track search failures and broken-link reports.
- Confirm no unresolved internal links from `npm run check:links`.
- Regenerate contributor metadata weekly or when major docs edits land:
  - `npm run contributors:generate`
