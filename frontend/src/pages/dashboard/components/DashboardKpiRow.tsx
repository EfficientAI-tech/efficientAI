import {
  FileCheck,
  Clock,
  CheckCircle,
  Phone,
  Users,
  Zap,
  TrendingUp,
  Activity,
} from 'lucide-react'
import { Card, CardBody, CardHeader, Progress, Skeleton } from '@heroui/react'
import { Link } from 'react-router-dom'
import type { DashboardSummary } from '../../../types/api'

interface DashboardKpiRowProps {
  summary?: DashboardSummary
  isLoading?: boolean
}

function StatItem({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string
  value: number
  icon: React.ComponentType<{ className?: string }>
  color: 'blue' | 'green' | 'amber' | 'red'
}) {
  const colorStyles = {
    blue: 'bg-[#fef9c3] text-[#a16207]',
    green: 'bg-[#e6f4ea] text-[#137333]',
    amber: 'bg-[#fef7e0] text-[#e37400]',
    red: 'bg-[#fce8e6] text-[#c5221f]',
  }

  return (
    <div className="text-center">
      <div
        className={`w-12 h-12 mx-auto rounded-2xl ${colorStyles[color]} flex items-center justify-center mb-3`}
      >
        <Icon className="w-6 h-6" />
      </div>
      <div className="text-3xl font-bold text-gray-900">{value}</div>
      <div className="text-sm text-gray-500 mt-1">{label}</div>
    </div>
  )
}

function ResourceItem({
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
  color: 'blue' | 'purple' | 'green' | 'orange'
}) {
  const colorStyles = {
    blue: 'bg-[#fef9c3] text-[#a16207]',
    purple: 'bg-[#f3e8ff] text-[#7c3aed]',
    green: 'bg-[#e6f4ea] text-[#137333]',
    orange: 'bg-[#fef3e2] text-[#ea8600]',
  }

  return (
    <Link to={href} className="flex items-center justify-between p-3 rounded-xl hover:bg-gray-50 transition-colors">
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-xl ${colorStyles[color]} flex items-center justify-center`}>
          <Icon className="w-5 h-5" />
        </div>
        <span className="text-sm font-medium text-gray-700">{label}</span>
      </div>
      <span className="text-lg font-bold text-gray-900">{value}</span>
    </Link>
  )
}

export default function DashboardKpiRow({ summary, isLoading }: DashboardKpiRowProps) {
  const completionRate =
    summary && summary.evaluations.total > 0
      ? Math.round((summary.evaluations.completed / summary.evaluations.total) * 100)
      : 0

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2 shadow-sm" radius="lg">
          <CardBody className="p-6 space-y-4">
            <Skeleton className="h-6 w-48 rounded-lg" />
            <div className="grid grid-cols-3 gap-6">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-24 rounded-xl" />
              ))}
            </div>
            <Skeleton className="h-2 w-full rounded-full" />
          </CardBody>
        </Card>
        <Card className="shadow-sm" radius="lg">
          <CardBody className="p-6 space-y-4">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-12 rounded-xl" />
            ))}
          </CardBody>
        </Card>
      </div>
    )
  }

  if (!summary) return null

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <Card className="lg:col-span-2 shadow-sm" radius="lg">
        <CardHeader className="pb-0 pt-5 px-6">
          <div className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-[#ca8a04]" />
            <h3 className="text-lg font-semibold text-gray-900">Evaluation Overview</h3>
          </div>
        </CardHeader>
        <CardBody className="p-6">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
            <StatItem label="Total" value={summary.evaluations.total} icon={FileCheck} color="blue" />
            <StatItem label="Completed" value={summary.evaluations.completed} icon={CheckCircle} color="green" />
            <StatItem label="Pending" value={summary.evaluations.pending} icon={Clock} color="amber" />
            <StatItem label="Failed" value={summary.evaluations.failed} icon={FileCheck} color="red" />
          </div>
          <div className="mt-6">
            <div className="flex justify-between items-center mb-2">
              <span className="text-sm text-gray-600">Completion Rate</span>
              <span className="text-sm font-semibold text-[#a16207]">{completionRate}%</span>
            </div>
            <Progress
              value={completionRate}
              className="h-2"
              classNames={{
                indicator: 'bg-gradient-to-r from-[#ca8a04] to-[#eab308]',
                track: 'bg-[#fef9c3]',
              }}
            />
          </div>
        </CardBody>
      </Card>

      <Card className="shadow-sm" radius="lg">
        <CardHeader className="pb-0 pt-5 px-6">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-[#34a853]" />
            <h3 className="text-lg font-semibold text-gray-900">Resources</h3>
          </div>
        </CardHeader>
        <CardBody className="p-6">
          <div className="space-y-1">
            <ResourceItem
              icon={Phone}
              label="Agents"
              value={summary.resources.agents}
              href="/agents"
              color="blue"
            />
            <ResourceItem
              icon={Users}
              label="Personas"
              value={summary.resources.personas}
              href="/personas"
              color="purple"
            />
            <ResourceItem
              icon={FileCheck}
              label="Scenarios"
              value={summary.resources.scenarios}
              href="/scenarios"
              color="green"
            />
            <ResourceItem
              icon={Zap}
              label="Integrations"
              value={summary.resources.integrations}
              href="/integrations"
              color="orange"
            />
          </div>
        </CardBody>
      </Card>
    </div>
  )
}
