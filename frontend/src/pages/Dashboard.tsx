import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import {
  FileCheck,
  Clock,
  CheckCircle,
  Loader,
  Users,
  Phone,
  Database,
  Zap,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { EvaluationStatus, Evaluation } from '../types/api'
import { format } from 'date-fns'
import VoiceAIModelsCarousel from '../components/VoiceAIModelsCarousel'

export default function Dashboard() {
  const { data: evaluations, isLoading: evalLoading } = useQuery({
    queryKey: ['evaluations', 'list'],
    queryFn: () => apiClient.listEvaluations(0, 10),
  })

  const { data: agents } = useQuery({
    queryKey: ['agents', 'list'],
    queryFn: () => apiClient.listAgents(0, 100),
  })

  const { data: personas } = useQuery({
    queryKey: ['personas', 'list'],
    queryFn: () => apiClient.listPersonas(0, 100),
  })

  const { data: scenarios } = useQuery({
    queryKey: ['scenarios', 'list'],
    queryFn: () => apiClient.listScenarios(0, 100),
  })

  const { data: integrations } = useQuery({
    queryKey: ['integrations'],
    queryFn: async () => {
      try {
        // Using direct API call due to TypeScript type issue (method exists at runtime)
        const apiKey = localStorage.getItem('apiKey') || ''
        const API_BASE_URL = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000'
        const response = await fetch(`${API_BASE_URL}/api/v1/integrations`, {
          headers: {
            'X-API-Key': apiKey,
            'Content-Type': 'application/json',
          },
        })
        if (!response.ok) return []
        return response.json()
      } catch {
        return []
      }
    },
  })

  const stats = {
    totalEvaluations: evaluations?.length || 0,
    completedEvaluations: evaluations?.filter(
      (e: Evaluation) => e.status === EvaluationStatus.COMPLETED
    ).length || 0,
    pendingEvaluations: evaluations?.filter(
      (e: Evaluation) => e.status === EvaluationStatus.PENDING
    ).length || 0,
  }

  const recentEvaluations = evaluations?.slice(0, 5) || []

  // Organization resources
  const orgResources = {
    agents: agents?.length || 0,
    personas: personas?.length || 0,
    scenarios: scenarios?.length || 0,
    integrations: integrations?.length || 0,
    totalEvaluations: stats.totalEvaluations,
    completedEvaluations: stats.completedEvaluations,
  }

  return (
    <div className="space-y-6">
      {/* Voice AI Models Carousel */}
      <div className="bg-gradient-to-br from-gray-50 to-gray-100 rounded-lg p-6 -mt-6">
        <div className="mb-4">
          <h2 className="text-xl font-semibold text-gray-900 mb-1">
            Latest Voice AI Models
          </h2>
          <p className="text-sm text-gray-600">
            Explore the newest voice AI models from leading providers
          </p>
        </div>
        <VoiceAIModelsCarousel />
      </div>

      {/* Organization Resources Highlights */}
      <div className="bg-white shadow rounded-lg p-6">
        <div className="mb-4">
          <h2 className="text-xl font-semibold text-gray-900 mb-1">
            Organization Resources
          </h2>
          <p className="text-sm text-gray-600">
            Overview of your provisioned resources
          </p>
        </div>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <ResourceCard
            icon={Phone}
            label="Agents"
            value={orgResources.agents}
            href="/agents"
            color="blue"
          />
          <ResourceCard
            icon={Users}
            label="Personas"
            value={orgResources.personas}
            href="/personas"
            color="purple"
          />
          <ResourceCard
            icon={FileCheck}
            label="Scenarios"
            value={orgResources.scenarios}
            href="/scenarios"
            color="green"
          />
          <ResourceCard
            icon={Zap}
            label="Integrations"
            value={orgResources.integrations}
            href="/integrations"
            color="orange"
          />
          <ResourceCard
            icon={Database}
            label="Total Evaluations"
            value={orgResources.totalEvaluations}
            href="/evaluations"
            color="indigo"
          />
          <ResourceCard
            icon={CheckCircle}
            label="Completed"
            value={orgResources.completedEvaluations}
            href="/evaluations?status=completed"
            color="emerald"
          />
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard
          title="Total Evaluations"
          value={stats.totalEvaluations}
          icon={FileCheck}
          color="green"
          href="/evaluations"
        />
        <StatCard
          title="Completed"
          value={stats.completedEvaluations}
          icon={CheckCircle}
          color="emerald"
          href="/evaluations?status=completed"
        />
        <StatCard
          title="Pending"
          value={stats.pendingEvaluations}
          icon={Clock}
          color="amber"
          href="/evaluations?status=pending"
        />
      </div>

      {/* Recent Evaluations */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-4 py-5 sm:p-6 border-b border-gray-200">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-medium text-gray-900">Recent Evaluations</h2>
            <Link
              to="/evaluations"
              className="text-sm text-primary-600 hover:text-primary-700"
            >
              View all →
            </Link>
          </div>
        </div>
        <div className="px-4 py-5 sm:p-6">
          {evalLoading ? (
            <div className="text-center py-8">
              <Loader className="h-8 w-8 animate-spin text-primary-600 mx-auto" />
            </div>
          ) : recentEvaluations.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              <FileCheck className="h-12 w-12 mx-auto mb-4 text-gray-400" />
              <p>No evaluations yet</p>
              <Link
                to="/evaluations"
                className="mt-4 inline-block text-primary-600 hover:text-primary-700"
              >
                Create your first evaluation →
              </Link>
            </div>
          ) : (
            <div className="flow-root">
              <ul className="-my-5 divide-y divide-gray-200">
                {recentEvaluations.map((evaluation: Evaluation) => (
                  <li key={evaluation.id} className="py-5">
                    <Link
                      to={`/evaluations/${evaluation.id}`}
                      className="block hover:bg-gray-50 -mx-4 px-4 py-4 rounded-lg transition-colors"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center">
                          <StatusBadge status={evaluation.status} />
                          <div className="ml-4">
                            <p className="text-sm font-medium text-gray-900">
                              Evaluation {evaluation.id.slice(0, 8)}...
                            </p>
                            <p className="text-sm text-gray-500">
                              {format(new Date(evaluation.created_at), 'MMM d, yyyy HH:mm')}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center">
                          <span className="text-sm text-gray-500">
                            {evaluation.evaluation_type}
                          </span>
                        </div>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function StatCard({
  title,
  value,
  icon: Icon,
  color,
  href,
}: {
  title: string
  value: number
  icon: React.ComponentType<{ className?: string }>
  color: string
  href?: string
}) {
  const colorClasses = {
    blue: 'bg-orange-500',
    green: 'bg-green-500',
    emerald: 'bg-emerald-500',
    amber: 'bg-amber-500',
  }

  const content = (
    <div className="bg-white overflow-hidden shadow rounded-lg">
      <div className="p-5">
        <div className="flex items-center">
          <div className={`flex-shrink-0 rounded-md p-3 ${colorClasses[color as keyof typeof colorClasses]}`}>
            <Icon className="h-6 w-6 text-white" />
          </div>
          <div className="ml-5 w-0 flex-1">
            <dl>
              <dt className="text-sm font-medium text-gray-500 truncate">{title}</dt>
              <dd className="flex items-baseline">
                <div className="text-2xl font-semibold text-gray-900">{value}</div>
              </dd>
            </dl>
          </div>
        </div>
      </div>
    </div>
  )

  if (href) {
    return <Link to={href}>{content}</Link>
  }

  return content
}

function ResourceCard({
  icon: Icon,
  label,
  value,
  href,
  color,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: number
  href: string
  color: string
}) {
  const colorClasses = {
    blue: 'bg-blue-100 text-blue-600',
    purple: 'bg-purple-100 text-purple-600',
    green: 'bg-green-100 text-green-600',
    orange: 'bg-orange-100 text-orange-600',
    indigo: 'bg-indigo-100 text-indigo-600',
    emerald: 'bg-emerald-100 text-emerald-600',
  }

  const content = (
    <div className="flex flex-col items-center p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors">
      <div className={`p-3 rounded-full ${colorClasses[color as keyof typeof colorClasses]}`}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="mt-2 text-center">
        <div className="text-2xl font-bold text-gray-900">{value}</div>
        <div className="text-xs text-gray-600 mt-1">{label}</div>
      </div>
    </div>
  )

  if (href) {
    return <Link to={href}>{content}</Link>
  }

  return content
}

function StatusBadge({ status }: { status: EvaluationStatus }) {
  const statusConfig = {
    [EvaluationStatus.PENDING]: {
      bg: 'bg-yellow-100',
      text: 'text-yellow-800',
      label: 'Pending',
    },
    [EvaluationStatus.PROCESSING]: {
      bg: 'bg-orange-100',
      text: 'text-orange-800',
      label: 'Processing',
    },
    [EvaluationStatus.COMPLETED]: {
      bg: 'bg-green-100',
      text: 'text-green-800',
      label: 'Completed',
    },
    [EvaluationStatus.FAILED]: {
      bg: 'bg-red-100',
      text: 'text-red-800',
      label: 'Failed',
    },
    [EvaluationStatus.CANCELLED]: {
      bg: 'bg-gray-100',
      text: 'text-gray-800',
      label: 'Cancelled',
    },
  }

  const config = statusConfig[status]

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${config.bg} ${config.text}`}>
      {config.label}
    </span>
  )
}

