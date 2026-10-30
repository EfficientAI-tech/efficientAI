import { useQuery } from '@tanstack/react-query'
import {
  Brain,
  Mic,
  Cloud,
  Users,
  Rocket,
  ArrowRight,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { Card, CardBody, Chip } from '@heroui/react'
import { apiClient } from '../../lib/api'
import SetupProgressHero from './components/SetupProgressHero'
import AnalyticsDashboard from './analytics/AnalyticsDashboard'
import { useMockDataStore } from './analytics/mockMode'

export default function Dashboard() {
  const mockEnabled = useMockDataStore((s) => s.enabled)
  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['dashboard', 'summary'],
    queryFn: () => apiClient.getDashboardSummary(),
    staleTime: 60 * 1000,
    enabled: !mockEnabled,
  })
  const { data: overview, isLoading: overviewLoading } = useQuery({
    queryKey: ['evaluator-results-overview', 'gate'],
    queryFn: () => apiClient.getEvaluatorResultsOverview(),
    staleTime: 60 * 1000,
    enabled: !mockEnabled,
  })

  // Sample data always renders the full analytics view so the dashboard
  // can be explored before the workspace has any scored runs.
  if (mockEnabled) {
    return <AnalyticsDashboard />
  }

  const hasRuns = (overview?.workspace_counts.total ?? 0) > 0
  const loading = (summaryLoading && !summary) || (overviewLoading && !overview)

  if (loading) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white px-4 py-10 text-sm text-gray-500">
        Loading dashboard…
      </div>
    )
  }

  if (!hasRuns) {
    return (
      <div className="space-y-6">
        {summary ? (
          <SetupProgressHero setupProgress={summary.setup_progress} />
        ) : (
          <OnboardingFallback />
        )}
      </div>
    )
  }

  return <AnalyticsDashboard />
}

function OnboardingFallback() {
  return (
    <Card className="bg-gradient-to-br from-[#fef9c3] to-[#fefce8] border-none shadow-sm" radius="lg">
      <CardBody className="p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-3 bg-[#ca8a04] rounded-2xl">
            <Rocket className="h-6 w-6 text-white" />
          </div>
          <div>
            <h2 className="text-2xl font-bold text-gray-900">Start Testing in 5 Minutes</h2>
            <p className="text-sm text-gray-600 mt-1">
              Follow these quick steps to get started with voice AI testing
            </p>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <QuickStartCard icon={Brain} title="Configure AI Provider" href="/settings/integrations" step={1} />
          <QuickStartCard icon={Mic} title="Create Voice Bundle" href="/voicebundles" step={2} />
          <QuickStartCard icon={Cloud} title="Connect Data Sources" href="/settings/cloud-storage" step={3} />
          <QuickStartCard icon={Users} title="Create Test Agent" href="/agents" step={4} />
        </div>
      </CardBody>
    </Card>
  )
}

function QuickStartCard({
  icon: Icon,
  title,
  href,
  step,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  href: string
  step: number
}) {
  return (
    <Link to={href}>
      <Card className="h-full hover:shadow-md transition-all bg-white/80 border-none" radius="lg" isPressable>
        <CardBody className="p-5">
          <Chip size="sm" className="bg-[#ca8a04] text-white font-semibold mb-3" radius="full">
            Step {step}
          </Chip>
          <div className="flex items-center gap-2 mb-2">
            <Icon className="h-5 w-5 text-[#ca8a04]" />
            <h3 className="text-base font-semibold text-gray-900">{title}</h3>
          </div>
          <div className="flex items-center gap-1 text-sm font-medium text-[#a16207]">
            Get started
            <ArrowRight className="h-4 w-4" />
          </div>
        </CardBody>
      </Card>
    </Link>
  )
}
