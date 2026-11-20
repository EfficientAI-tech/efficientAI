import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Play } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { itemsOf } from '../../lib/safeData'
import Button from '../../components/Button'
import StudioRunWizard from './components/studioWizard/StudioRunWizard'
import StudioResultsList from './components/studioWizard/StudioResultsList'
import StudioSubTabs, { studioTabFromSearch } from './components/studioWizard/StudioSubTabs'

export default function MetricsStudio() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const activeTab = studioTabFromSearch(searchParams.get('tab'))

  const [wizardOpen, setWizardOpen] = useState(false)

  const { data: runsData, isLoading: runsLoading } = useQuery({
    queryKey: ['metric-studio-runs'],
    queryFn: () => apiClient.listMetricStudioRuns(),
    refetchInterval: (query) => {
      const items = itemsOf(query.state.data)
      return items.some((r: any) => r.status === 'running' || r.status === 'pending')
        ? 3000
        : false
    },
  })

  return (
    <div className="space-y-6">
      <StudioSubTabs />

      {activeTab === 'setup' ? (
        <section className="rounded-lg border border-gray-200 bg-white p-8">
          <h2 className="text-lg font-semibold text-gray-900">Run ad-hoc evaluations</h2>
          <p className="mt-2 text-sm text-gray-600 max-w-2xl">
            Choose call sources, metrics, and an optional evaluation model in a guided flow.
            Results appear on the Results tab and in run detail while scoring completes.
          </p>
          <div className="mt-6">
            <Button
              variant="primary"
              size="lg"
              leftIcon={<Play className="h-4 w-4" />}
              onClick={() => setWizardOpen(true)}
            >
              New evaluation
            </Button>
          </div>
        </section>
      ) : (
        <StudioResultsList
          runsData={runsData}
          runsLoading={runsLoading}
          onRefresh={() => queryClient.invalidateQueries({ queryKey: ['metric-studio-runs'] })}
        />
      )}

      <StudioRunWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        onRunCreated={(runId) => navigate(`/metrics-management/studio/runs/${runId}`)}
      />
    </div>
  )
}
