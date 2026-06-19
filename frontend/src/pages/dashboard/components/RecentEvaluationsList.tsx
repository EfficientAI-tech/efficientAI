import { Link } from 'react-router-dom'
import { format } from 'date-fns'
import { FileCheck, ArrowRight } from 'lucide-react'
import { Card, CardBody, CardHeader, Divider, Avatar, Skeleton } from '@heroui/react'
import type { Evaluation } from '../../../types/api'
import StatusChip from './StatusChip'

interface RecentEvaluationsListProps {
  evaluations: Evaluation[]
  isLoading?: boolean
}

export default function RecentEvaluationsList({ evaluations, isLoading }: RecentEvaluationsListProps) {
  return (
    <Card className="shadow-sm h-full" radius="lg">
      <CardHeader className="px-6 py-4">
        <div className="flex items-center justify-between w-full">
          <h3 className="text-lg font-semibold text-gray-900">Recent Evaluations</h3>
          <Link
            to="/evaluations"
            className="text-sm text-[#a16207] hover:text-[#854d0e] font-medium flex items-center gap-1"
          >
            View all
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </CardHeader>
      <Divider />
      <CardBody className="p-0">
        {isLoading ? (
          <div className="p-6 space-y-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex items-center gap-4">
                <Skeleton className="w-8 h-8 rounded-full" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-40 rounded-lg" />
                  <Skeleton className="h-3 w-28 rounded-lg" />
                </div>
              </div>
            ))}
          </div>
        ) : evaluations.length === 0 ? (
          <div className="text-center py-12">
            <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-[#fef9c3] flex items-center justify-center">
              <FileCheck className="h-8 w-8 text-[#ca8a04]" />
            </div>
            <p className="text-gray-500 mb-2">No evaluations yet</p>
            <Link to="/metrics" className="text-[#a16207] hover:text-[#854d0e] font-medium text-sm">
              Create your first evaluation →
            </Link>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {evaluations.map((evaluation) => (
              <Link
                key={evaluation.id}
                to={`/evaluations/${evaluation.id}`}
                className="flex items-center justify-between px-6 py-4 hover:bg-gray-50 transition-colors"
              >
                <div className="flex items-center gap-4 min-w-0">
                  <Avatar
                    name={evaluation.id.slice(0, 2).toUpperCase()}
                    size="sm"
                    className="bg-[#fef9c3] text-[#a16207] flex-shrink-0"
                  />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      Evaluation {evaluation.id.slice(0, 8)}...
                    </p>
                    <p className="text-xs text-gray-500">
                      {format(new Date(evaluation.created_at), 'MMM d, yyyy HH:mm')}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <span className="text-xs text-gray-500 hidden sm:inline">{evaluation.evaluation_type}</span>
                  <StatusChip status={evaluation.status} />
                </div>
              </Link>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  )
}
