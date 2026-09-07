import { AlertTriangle } from 'lucide-react'
import {
  formatInboundTtsMismatchMessage,
  formatTtsMismatchMessage,
  suiteHasTtsProviderMismatch,
  type TtsMismatchSuiteLike,
} from '../utils/evaluatorTtsMismatch'

interface Props {
  suite: TtsMismatchSuiteLike
  variant?: 'block' | 'inform'
  onEditPersonas?: () => void
}

export default function EvaluatorTtsMismatchBanner({
  suite,
  variant = 'block',
  onEditPersonas,
}: Props) {
  if (!suiteHasTtsProviderMismatch(suite)) return null

  const message =
    variant === 'inform'
      ? formatInboundTtsMismatchMessage(suite)
      : formatTtsMismatchMessage(suite)

  return (
    <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
      <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
      <div className="space-y-2">
        <p>{message}</p>
        {onEditPersonas && variant === 'block' && (
          <button
            type="button"
            onClick={onEditPersonas}
            className="font-medium text-red-800 underline underline-offset-2 hover:text-red-950"
          >
            Edit evaluator personas
          </button>
        )}
      </div>
    </div>
  )
}
