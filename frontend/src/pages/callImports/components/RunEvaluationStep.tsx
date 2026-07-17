import { PlayCircle } from 'lucide-react'
import Button from '../../../components/Button'

interface RunEvaluationStepProps {
  onRunEvaluation: () => void
  disabled?: boolean
}

/**
 * Step 3 panel shown below mapping once the batch reaches ``mapped``.
 * Keeps the primary CTA at the bottom of the staged workflow instead of
 * the page header, which matches the three-step tracker above.
 */
export default function RunEvaluationStep({
  onRunEvaluation,
  disabled = false,
}: RunEvaluationStepProps) {
  return (
    <div className="bg-white shadow rounded-lg p-6 border-2 border-primary-100">
      <div className="flex items-start gap-4">
        <div className="h-10 w-10 rounded-full bg-primary-100 text-primary-700 flex items-center justify-center flex-shrink-0">
          <PlayCircle className="h-5 w-5" />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-lg font-semibold text-gray-900">3. Run Evaluation</h2>
          <p className="mt-1 text-sm text-gray-600">
            Fetches recordings, diarizes transcripts, and scores each row against
            your selected metrics.
          </p>
          <div className="mt-4 flex justify-end">
            <Button
              variant="primary"
              onClick={onRunEvaluation}
              disabled={disabled}
              leftIcon={<PlayCircle className="h-4 w-4" />}
            >
              Run Evaluation
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
