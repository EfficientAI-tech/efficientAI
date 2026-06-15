# Docs Cutover and Stabilization

This runbook tracks the Fumadocs rollout strategy.

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

- Track search failures and broken-link reports.
- Confirm no unresolved internal links from `npm run check:links`.
