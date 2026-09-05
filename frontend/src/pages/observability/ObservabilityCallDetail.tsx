import { Navigate, useParams } from 'react-router-dom'

export default function ObservabilityCallDetail() {
  const { callShortId } = useParams<{ callShortId: string }>()
  if (!callShortId) return <Navigate to="/observability/calls" replace />
  return <Navigate to={`/observability/calls?obs=${callShortId}`} replace />
}
