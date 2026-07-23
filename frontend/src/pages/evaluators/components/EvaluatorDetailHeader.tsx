import { ArrowLeft, Edit2, Save, Play, Trash2, CheckCircle2 } from 'lucide-react'
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
  isActive?: boolean
  isSaving: boolean
  isActivating?: boolean
  isDeleting?: boolean
  onEdit: () => void
  onCancelEdit: () => void
  onSave: () => void
  onRun?: () => void
  onActivate?: () => void
  onDelete: () => void
}

export default function EvaluatorDetailHeader({
  title,
  subtitle,
  callMedium,
  callType,
  isEditing,
  isInbound,
  isActive,
  isSaving,
  isActivating,
  onEdit,
  onCancelEdit,
  onSave,
  onRun,
  onActivate,
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
            {isInbound && isActive && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
                <CheckCircle2 className="h-3 w-3" />
                Active for inbound
              </span>
            )}
            {isInbound && isActive === false && (
              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-800 border border-amber-200">
                Inactive
              </span>
            )}
          </div>
          {subtitle && (
            <p className="text-sm text-gray-500 mt-1">{subtitle}</p>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 shrink-0">
        {!isEditing && isInbound && !isActive && onActivate && (
          <Button
            variant="primary"
            onClick={onActivate}
            isLoading={isActivating}
            leftIcon={<CheckCircle2 className="w-4 h-4" />}
          >
            Set as active
          </Button>
        )}
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
