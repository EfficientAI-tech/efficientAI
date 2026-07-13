import { ArrowLeft, Edit2, Save, Play, Trash2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Button from '../../../components/Button'
import { CallTypeBadge } from './evaluatorUi'

interface Props {
  title: string
  subtitle?: string
  callMedium?: string | null
  callType?: string | null
  isEditing: boolean
  isInbound: boolean
  isSaving: boolean
  isDeleting?: boolean
  onEdit: () => void
  onCancelEdit: () => void
  onSave: () => void
  onRun?: () => void
  onDelete: () => void
}

export default function EvaluatorDetailHeader({
  title,
  subtitle,
  callMedium,
  callType,
  isEditing,
  isInbound,
  isSaving,
  onEdit,
  onCancelEdit,
  onSave,
  onRun,
  onDelete,
}: Props) {
  const navigate = useNavigate()

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex items-start gap-4 min-w-0">
        <Button onClick={() => navigate('/evaluate-test-agents')} variant="outline" size="sm">
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back
        </Button>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold text-gray-900 truncate">{title}</h1>
            <CallTypeBadge medium={callMedium} callType={callType} />
          </div>
          {subtitle && (
            <p className="text-sm text-gray-500 mt-1">{subtitle}</p>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 shrink-0">
        {!isEditing && !isInbound && onRun && (
          <Button variant="primary" onClick={onRun} leftIcon={<Play className="w-4 h-4" />}>
            Run Suite
          </Button>
        )}
        {!isEditing ? (
          <>
            <Button variant="outline" onClick={onEdit} leftIcon={<Edit2 className="w-4 h-4" />}>
              Edit
            </Button>
            <Button
              variant="ghost"
              onClick={onDelete}
              leftIcon={<Trash2 className="w-4 h-4" />}
              className="text-red-600 hover:text-red-700 hover:bg-red-50"
            >
              Delete
            </Button>
          </>
        ) : (
          <>
            <Button variant="outline" onClick={onCancelEdit}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={onSave}
              isLoading={isSaving}
              leftIcon={<Save className="w-4 h-4" />}
            >
              Save Changes
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
