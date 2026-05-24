import { Check, UploadCloud, Layers, PlayCircle } from 'lucide-react'
import type { CallImportStatus } from '../../../types/api'

/**
 * Three-step tracker at the top of the call-import detail page.
 *
 * Drives the user through the staged flow:
 *   1. Uploaded -> file landed in S3.
 *   2. Mapped   -> schema + sheet + parameter mapping persisted.
 *   3. Imported -> rows materialised, workers enqueued.
 *
 * The "imported" step covers every terminal status (processing /
 * completed / partial / failed) since "import has begun" is the
 * meaningful transition for the user, not the worker's verdict.
 *
 * Returns ``completedThrough`` — the index of the most recently
 * *finished* stage. The stage at ``completedThrough + 1`` is what
 * the user is currently working on (rendered as "active"); anything
 * at-or-before ``completedThrough`` gets a green check.
 */
function statusStage(status: CallImportStatus): 0 | 1 | 2 | 3 {
  if (status === 'uploaded') return 1 // UPLOAD done, MAP is next
  if (status === 'mapped') return 2 // UPLOAD + MAP done, IMPORT is next
  // Anything else (pending / processing / completed / partial / failed)
  // means the IMPORT step has already been kicked off — every stage
  // is in the past at that point.
  return 3
}

interface StageTrackerProps {
  status: CallImportStatus
}

const STAGES: Array<{
  index: 1 | 2 | 3
  label: string
  description: string
  Icon: typeof UploadCloud
}> = [
  {
    index: 1,
    label: 'Uploaded',
    description: 'Source file is staged and ready to map.',
    Icon: UploadCloud,
  },
  {
    index: 2,
    label: 'Mapped',
    description: 'Schema, sheet and parameter mapping persisted.',
    Icon: Layers,
  },
  {
    index: 3,
    label: 'Imported',
    description: 'Rows materialised; recordings fetched in the background.',
    Icon: PlayCircle,
  },
]

export default function StageTracker({ status }: StageTrackerProps) {
  const completedThrough = statusStage(status)
  return (
    <div className="bg-white shadow rounded-lg p-4">
      <ol className="flex items-start gap-3">
        {STAGES.map((stage) => {
          const done = stage.index <= completedThrough
          const active = stage.index === completedThrough + 1
          const Icon = stage.Icon
          return (
            <li key={stage.index} className="flex-1 min-w-0">
              <div className="flex items-center gap-3">
                <div
                  className={`h-9 w-9 rounded-full flex items-center justify-center flex-shrink-0 ${
                    done
                      ? 'bg-green-100 text-green-700'
                      : active
                        ? 'bg-primary-100 text-primary-700'
                        : 'bg-gray-100 text-gray-400'
                  }`}
                >
                  {done ? (
                    <Check className="h-4 w-4" />
                  ) : (
                    <Icon className="h-4 w-4" />
                  )}
                </div>
                <div className="min-w-0">
                  <div
                    className={`text-sm font-semibold ${
                      done || active ? 'text-gray-900' : 'text-gray-500'
                    }`}
                  >
                    {stage.index}. {stage.label}
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5 truncate">
                    {stage.description}
                  </p>
                </div>
              </div>
              {/* Render an underline under every stage (not just the
                  first two) so a fully-imported batch looks symmetric.
                  The colour still tracks ``done`` so stages the user
                  hasn't reached yet stay gray. */}
              <div
                className={`mt-3 ml-9 h-0.5 ${
                  done ? 'bg-green-300' : 'bg-gray-200'
                }`}
                aria-hidden="true"
              />
            </li>
          )
        })}
      </ol>
    </div>
  )
}
