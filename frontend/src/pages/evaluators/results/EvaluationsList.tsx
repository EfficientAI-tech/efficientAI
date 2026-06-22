import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { format } from 'date-fns'
import { FileCheck, ArrowLeft, Loader } from 'lucide-react'
import { apiClient } from '../../../lib/api'
import { Card, CardBody, Avatar } from '@heroui/react'
import StatusChip from '../../dashboard/components/StatusChip'

export default function EvaluationsList() {
  const { data: evaluations = [], isLoading } = useQuery({
    queryKey: ['evaluations', 'list'],
    queryFn: () => apiClient.listEvaluations(0, 100),
  })

  return (
    <div className="space-y-6">
      <div>
        <Link
          to="/"
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 mb-4"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </Link>
        <h1 className="text-2xl font-bold text-gray-900">Evaluations</h1>
        <p className="text-sm text-gray-600 mt-1">Audio ASR and TTS evaluation jobs</p>
      </div>

      <Card className="shadow-sm" radius="lg">
        <CardBody className="p-0">
          {isLoading ? (
            <div className="flex justify-center py-16">
              <Loader className="h-8 w-8 animate-spin text-[#ca8a04]" />
            </div>
          ) : evaluations.length === 0 ? (
            <div className="text-center py-16">
              <FileCheck className="h-12 w-12 text-gray-300 mx-auto mb-4" />
              <p className="text-gray-500 mb-2">No evaluations yet</p>
              <Link to="/metrics" className="text-[#a16207] hover:text-[#854d0e] font-medium text-sm">
                Start an evaluation →
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
                      className="bg-[#fef9c3] text-[#a16207]"
                    />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-900">
                        Evaluation {evaluation.id.slice(0, 8)}...
                      </p>
                      <p className="text-xs text-gray-500">
                        {format(new Date(evaluation.created_at), 'MMM d, yyyy HH:mm')} ·{' '}
                        {evaluation.evaluation_type}
                      </p>
                    </div>
                  </div>
                  <StatusChip status={evaluation.status} />
                </Link>
              ))}
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
