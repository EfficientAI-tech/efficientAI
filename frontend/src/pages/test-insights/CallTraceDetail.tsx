import { Navigate, useParams } from 'react-router-dom'

export default function CallTraceDetail() {
  const { traceId } = useParams<{ traceId: string }>()
  if (!traceId) return <Navigate to="/calls" replace />
  return <Navigate to={`/calls?trace=${traceId}`} replace />
}
