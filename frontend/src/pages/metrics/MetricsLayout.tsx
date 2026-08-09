import { Outlet } from 'react-router-dom'
import MetricsTabBar from './components/MetricsTabBar'

export default function MetricsLayout() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Metrics</h1>
        <p className="mt-2 text-sm text-gray-600 max-w-2xl">
          Define quality metrics for your agents, or experiment with draft
          metrics and ad-hoc evaluations in Studio.
        </p>
      </div>
      <MetricsTabBar />
      <Outlet />
    </div>
  )
}
