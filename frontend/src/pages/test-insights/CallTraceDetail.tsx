import { Navigate, useParams } from 'react-router-dom'

export default function CallTraceDetail() {
  const { traceId } = useParams<{ traceId: string }>()
  if (!traceId) return <Navigate to="/call-traces" replace />
  return <Navigate to={`/call-traces?trace=${traceId}`} replace />
}
