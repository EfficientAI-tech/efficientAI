import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import {
  Music,
  FileCheck,
  FolderSync,
  TrendingUp,
  Clock,
  CheckCircle,
  XCircle,
  Loader,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { EvaluationStatus } from '../types/api'
import { format } from 'date-fns'

export default function Dashboard() {
  const { data: audioFiles, isLoading: audioLoading } = useQuery({
    queryKey: ['audio', 'list'],
    queryFn: () => apiClient.listAudio(0, 10),
  })

  const { data: evaluations, isLoading: evalLoading } = useQuery({
    queryKey: ['evaluations', 'list'],
    queryFn: () => apiClient.listEvaluations(0, 10),
  })

  const stats = {
    totalAudio: audioFiles?.length || 0,
    totalEvaluations: evaluations?.length || 0,
    completedEvaluations: evaluations?.filter(
      (e) => e.status === EvaluationStatus.COMPLETED
    ).length || 0,
    pendingEvaluations: evaluations?.filter(
      (e) => e.status === EvaluationStatus.PENDING
    ).length || 0,
  }

  const recentEvaluations = evaluations?.slice(0, 5) || []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
        <p className="mt-2 text-sm text-gray-600">
          Overview of your Voice AI Evaluation Platform
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Audio Files"
          value={stats.totalAudio}
          icon={Music}
          color="blue"
          href="/audio"
        />
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
                {recentEvaluations.map((evaluation) => (
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
    blue: 'bg-blue-500',
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

function StatusBadge({ status }: { status: EvaluationStatus }) {
  const statusConfig = {
    [EvaluationStatus.PENDING]: {
      bg: 'bg-yellow-100',
      text: 'text-yellow-800',
      label: 'Pending',
    },
    [EvaluationStatus.PROCESSING]: {
      bg: 'bg-blue-100',
      text: 'text-blue-800',
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

