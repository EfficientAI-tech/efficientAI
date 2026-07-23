/** Display status for evaluator results (handles stale in-flight status when scores exist). */

export type EvaluatorResultStatus =
  | 'queued'
  | 'call_initiating'
  | 'call_connecting'
  | 'call_in_progress'
  | 'call_ended'
  | 'transcribing'
  | 'evaluating'
  | 'fetching_details'
  | 'completed'
  | 'failed'

const IN_FLIGHT_WITH_SCORES: EvaluatorResultStatus[] = [
  'queued',
  'transcribing',
  'evaluating',
  'fetching_details',
]

export function displayEvaluatorResultStatus(result: {
  status: EvaluatorResultStatus
  metric_scores?: Record<string, unknown> | null
}): EvaluatorResultStatus {
  const scores = result.metric_scores
  if (scores && Object.keys(scores).length > 0 && IN_FLIGHT_WITH_SCORES.includes(result.status)) {
    return 'completed'
  }
  return result.status
}

export function isEvaluatorResultInProgress(status: EvaluatorResultStatus): boolean {
  return [
    'queued',
    'call_initiating',
    'call_connecting',
    'call_in_progress',
    'call_ended',
    'transcribing',
    'evaluating',
    'fetching_details',
  ].includes(status)
}
