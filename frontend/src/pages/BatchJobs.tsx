import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Plus,
  Loader,
  FolderSync,
  RefreshCw,
  CheckCircle,
  Clock,
  XCircle,
} from 'lucide-react'
import { format } from 'date-fns'
import CreateBatchModal from '../components/CreateBatchModal'
import Button from '../components/Button'

export default function BatchJobs() {
  const [showCreateModal, setShowCreateModal] = useState(false)

  // Note: There's no list batch endpoint, so we'd need to track batch IDs
  // For now, we'll show a placeholder with create functionality
  const { data: batches, isLoading } = useQuery({
    queryKey: ['batches'],
    queryFn: async () => {
      // This would need a backend endpoint to list all batches
      // For now, return empty array
      return []
    },
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Batch Jobs</h1>
          <p className="mt-2 text-sm text-gray-600">
            Process multiple audio files in parallel
          </p>
        </div>
        <Button
          onClick={() => setShowCreateModal(true)}
          leftIcon={<Plus className="h-4 w-4" />}
        >
          New Batch Job
        </Button>
      </div>

      {isLoading ? (
        <div className="text-center py-12">
          <Loader className="h-8 w-8 animate-spin text-primary-600 mx-auto" />
        </div>
      ) : !batches || batches.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <FolderSync className="h-12 w-12 mx-auto mb-4 text-gray-400" />
          <p className="text-gray-500">No batch jobs yet</p>
          <Button
            variant="ghost"
            onClick={() => setShowCreateModal(true)}
            className="mt-4"
          >
            Create your first batch job →
          </Button>
        </div>
      ) : (
        <div className="bg-white shadow overflow-hidden sm:rounded-md">
          <ul className="divide-y divide-gray-200">
            {batches.map((batch: any) => (
              <li key={batch.id}>
                <Link
                  to={`/batch/${batch.id}`}
                  className="block hover:bg-gray-50 transition-colors"
                >
                  <div className="px-4 py-4 sm:px-6">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center">
                        <StatusIcon status={batch.status} />
                        <div className="ml-4">
                          <p className="text-sm font-medium text-gray-900">
                            Batch {batch.id.slice(0, 8)}...
                          </p>
                          <div className="mt-1 flex items-center text-sm text-gray-500 space-x-4">
                            <span>{format(new Date(batch.created_at), 'MMM d, yyyy HH:mm')}</span>
                            <span>•</span>
                            <span>{batch.total_files} files</span>
                            <span>•</span>
                            <span>{batch.processed_files} processed</span>
                          </div>
                        </div>
                      </div>
                      <StatusBadge status={batch.status} />
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {showCreateModal && (
        <CreateBatchModal
          isOpen={showCreateModal}
          onClose={() => setShowCreateModal(false)}
        />
      )}
    </div>
  )
}

function StatusIcon({ status }: { status: string }) {
  const iconConfig: Record<string, { Icon: React.ComponentType<{ className?: string }>, color: string }> = {
    pending: { Icon: Clock, color: 'text-yellow-500' },
    processing: { Icon: RefreshCw, color: 'text-orange-500 animate-spin' },
    completed: { Icon: CheckCircle, color: 'text-green-500' },
    failed: { Icon: XCircle, color: 'text-red-500' },
    cancelled: { Icon: XCircle, color: 'text-gray-500' },
  }

  const config = iconConfig[status] || iconConfig.pending
  const { Icon, color } = config
  return <Icon className={`h-5 w-5 ${color}`} />
}

function StatusBadge({ status }: { status: string }) {
  const statusConfig: Record<string, { bg: string; text: string; label: string }> = {
    pending: { bg: 'bg-yellow-100', text: 'text-yellow-800', label: 'Pending' },
    processing: { bg: 'bg-orange-100', text: 'text-orange-800', label: 'Processing' },
    completed: { bg: 'bg-green-100', text: 'text-green-800', label: 'Completed' },
    failed: { bg: 'bg-red-100', text: 'text-red-800', label: 'Failed' },
    cancelled: { bg: 'bg-gray-100', text: 'text-gray-800', label: 'Cancelled' },
  }

  const config = statusConfig[status] || statusConfig.pending
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${config.bg} ${config.text}`}
    >
      {config.label}
    </span>
  )
}

