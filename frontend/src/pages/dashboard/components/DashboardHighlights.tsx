import { Link } from 'react-router-dom'
import {
  FileCheck,
  CheckCircle,
  Clock,
  BarChart3,
  Upload,
  ArrowRight,
  Activity,
} from 'lucide-react'
import { Card, CardBody, CardHeader, Progress, Skeleton } from '@heroui/react'
import type { DashboardSummary } from '../../../types/api'

interface DashboardHighlightsProps {
  summary?: DashboardSummary
  isLoading?: boolean
}

function HighlightStat({
  label,
  value,
  sublabel,
}: {
  label: string
  value: number
  sublabel?: string
}) {
  return (
    <div>
      <div className="text-2xl font-bold text-gray-900 tabular-nums">{value}</div>
      <div className="text-sm text-gray-600">{label}</div>
      {sublabel && <div className="text-xs text-gray-500 mt-0.5">{sublabel}</div>}
    </div>
  )
}

export default function DashboardHighlights({ summary, isLoading }: DashboardHighlightsProps) {
  if (isLoading && !summary) {
    return (
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-40 rounded-2xl" />
        ))}
      </div>
    )
  }

  if (!summary) return null

  const completionRate =
    summary.evaluations.total > 0
      ? Math.round((summary.evaluations.completed / summary.evaluations.total) * 100)
      : 0

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Audio evaluations */}
      <Card className="shadow-sm" radius="lg">
        <CardHeader className="pb-0 pt-5 px-6">
          <div className="flex items-center justify-between w-full">
            <div className="flex items-center gap-2">
              <Activity className="w-5 h-5 text-[#ca8a04]" />
              <h3 className="text-lg font-semibold text-gray-900">Evaluations</h3>
            </div>
            <Link
              to="/evaluations"
              className="text-sm text-[#a16207] hover:text-[#854d0e] font-medium flex items-center gap-1"
            >
              View all
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </CardHeader>
        <CardBody className="p-6">
          <div className="grid grid-cols-3 gap-4 mb-5">
            <HighlightStat label="Total" value={summary.evaluations.total} />
            <HighlightStat label="Completed" value={summary.evaluations.completed} />
            <HighlightStat label="Pending" value={summary.evaluations.pending} />
          </div>
          <div>
            <div className="flex justify-between items-center mb-2">
              <span className="text-sm text-gray-600">Completion rate</span>
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

      {/* Metrics */}
      <Card className="shadow-sm" radius="lg">
        <CardHeader className="pb-0 pt-5 px-6">
          <div className="flex items-center justify-between w-full">
            <div className="flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-[#34a853]" />
              <h3 className="text-lg font-semibold text-gray-900">Metrics</h3>
            </div>
            <Link
              to="/metrics-management"
              className="text-sm text-[#a16207] hover:text-[#854d0e] font-medium flex items-center gap-1"
            >
              Manage
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </CardHeader>
        <CardBody className="p-6">
          <div className="grid grid-cols-2 gap-6">
            <HighlightStat
              label="Total metrics"
              value={summary.metrics.total}
              sublabel="Workspace + org-shared"
            />
            <HighlightStat
              label="Enabled"
              value={summary.metrics.enabled}
              sublabel="Active for scoring"
            />
          </div>
          <p className="text-sm text-gray-500 mt-6">
            Define rubrics for agent, voice playground, and call-import scoring.
          </p>
        </CardBody>
      </Card>

      {/* Call imports & import evaluations */}
      <Card className="shadow-sm" radius="lg">
        <CardHeader className="pb-0 pt-5 px-6">
          <div className="flex items-center justify-between w-full">
            <div className="flex items-center gap-2">
              <Upload className="w-5 h-5 text-[#7c3aed]" />
              <h3 className="text-lg font-semibold text-gray-900">Call Imports</h3>
            </div>
            <Link
              to="/call-imports"
              className="text-sm text-[#a16207] hover:text-[#854d0e] font-medium flex items-center gap-1"
            >
              View imports
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </CardHeader>
        <CardBody className="p-6">
          <div className="grid grid-cols-2 gap-4 mb-4">
            <HighlightStat
              label="Import batches"
              value={summary.call_imports.total}
            />
            <HighlightStat
              label="Eval runs done"
              value={summary.call_import_evaluations.completed}
              sublabel={`${summary.call_import_evaluations.total} total runs`}
            />
          </div>
          <div className="flex flex-wrap gap-3 text-xs">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#e6f4ea] text-[#137333]">
              <CheckCircle className="w-3.5 h-3.5" />
              {summary.call_import_evaluations.completed} completed
            </span>
            {summary.call_import_evaluations.running > 0 && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#fef7e0] text-[#e37400]">
                <Clock className="w-3.5 h-3.5" />
                {summary.call_import_evaluations.running} running
              </span>
            )}
            {summary.call_import_evaluations.failed > 0 && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#fce8e6] text-[#c5221f]">
                <FileCheck className="w-3.5 h-3.5" />
                {summary.call_import_evaluations.failed} failed
              </span>
            )}
          </div>
        </CardBody>
      </Card>
    </div>
  )
}
