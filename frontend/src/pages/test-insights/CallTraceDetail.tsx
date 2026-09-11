import { Navigate, useParams } from 'react-router-dom'

export default function CallTraceDetail() {
  const { traceId } = useParams<{ traceId: string }>()
  if (!traceId) return <Navigate to="/observability/calls" replace />
  return <Navigate to={`/observability/calls?trace=${traceId}`} replace />
}
