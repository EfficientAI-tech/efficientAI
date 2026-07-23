import { Edit2, Save, X } from 'lucide-react'
import Button from '../../../components/Button'

interface AgentDetailHeaderProps {
  agentName?: string
  agentId?: string | null
  isEditMode: boolean
  isPending: boolean
  onEditClick: () => void
  onCancelEdit: () => void
  onSave: () => void
  /** When true, omits the title block (name shown elsewhere). */
  hideTitle?: boolean
}

export default function AgentDetailHeader({
  agentName,
  agentId,
  isEditMode,
  isPending,
  onEditClick,
  onCancelEdit,
  onSave,
  hideTitle = false,
}: AgentDetailHeaderProps) {
  return (
    <div className={`flex items-center gap-2 shrink-0 ${hideTitle ? '' : 'flex-col sm:flex-row sm:justify-between w-full'}`}>
      {!hideTitle && (
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-bold text-gray-900 truncate">
            {isEditMode ? 'Edit Agent' : agentName || 'Agent Details'}
          </h1>
          {agentId && (
            <p className="text-sm text-gray-500 mt-0.5">
              Agent ID: <span className="font-mono font-semibold text-primary-600">{agentId}</span>
            </p>
          )}
        </div>
      )}
      <div className="flex items-center gap-2">
        {!isEditMode ? (
          <button
            type="button"
            onClick={onEditClick}
            className="inline-flex items-center justify-center h-9 w-9 rounded-lg border border-gray-200 bg-white text-gray-600 hover:text-primary-600 hover:border-primary-300 hover:bg-primary-50 transition-colors"
            title="Edit agent"
            aria-label="Edit agent"
          >
            <Edit2 className="h-4 w-4" />
          </button>
        ) : (
          <>
            <Button
              onClick={onCancelEdit}
              variant="outline"
              size="sm"
              leftIcon={<X className="h-3.5 w-3.5" />}
            >
              Cancel
            </Button>
            <Button
              onClick={onSave}
              variant="primary"
              size="sm"
              leftIcon={<Save className="h-3.5 w-3.5" />}
              isLoading={isPending}
            >
              Save
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
