import TraceDetailDrawer from '../../../components/call-recordings/TraceDetailDrawer'
import {
  readPersistedResultsHubQueryString,
  resultsDetailHref,
} from './resultsHubNavigation'

/** Charts / dashboard drill-down only — not used from the Runs tab. */
export default function ResultsRunDetailDrawer({
  resultId,
  onClose,
  workspaceId,
}: {
  resultId: string | null
  onClose: () => void
  workspaceId?: string | null
}) {
  const fullDetailHref = resultId
    ? resultsDetailHref(resultId, readPersistedResultsHubQueryString(workspaceId))
    : undefined

  return (
    <TraceDetailDrawer
      open={Boolean(resultId)}
      evaluatorResultId={resultId}
      onClose={onClose}
      chartDrilldown
      fullDetailHref={fullDetailHref}
    />
  )
}

/** Prefer UUID `id` from list rows; fall back to display `result_id` when needed. */
export function evaluatorResultOpenId(row: {
  id: string
  result_id?: string | null
}): string {
  return row.id || String(row.result_id || '')
}