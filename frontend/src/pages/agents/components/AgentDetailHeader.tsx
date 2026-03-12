import { ArrowLeft, Edit2, Save } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Button from '../../../components/Button'

interface AgentDetailHeaderProps {
  agentId?: string | null
  isEditMode: boolean
  isPending: boolean
  onEditClick: () => void
  onCancelEdit: () => void
  onSave: () => void
}

export default function AgentDetailHeader({
  agentId,
  isEditMode,
  isPending,
  onEditClick,
  onCancelEdit,
  onSave,
}: AgentDetailHeaderProps) {
  const navigate = useNavigate()

  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-4">
        <Button onClick={() => navigate('/agents')} variant="outline">
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back to Agents
        </Button>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            {isEditMode ? 'Edit Agent' : 'Agent Details'}
          </h1>
          {agentId && (
            <p className="text-sm text-gray-500 mt-1">
              Agent ID: <span className="font-mono font-semibold text-blue-600">{agentId}</span>
            </p>
          )}
        </div>
      </div>
      <div className="flex items-center gap-3">
        {!isEditMode ? (
          <Button
            onClick={onEditClick}
            variant="primary"
            leftIcon={<Edit2 className="w-4 h-4" />}
          >
            Edit
          </Button>
        ) : (
          <>
            <Button onClick={onCancelEdit} variant="outline">
              Cancel
            </Button>
            <Button
              onClick={onSave}
              variant="primary"
              leftIcon={<Save className="w-4 h-4" />}
              isLoading={isPending}
            >
              Save Changes
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
