import { asArray } from './safeData'

/** Safe reads for playground / call-recording evaluation fields (avoid render crashes). */

export function evaluationStatusFromRecording(
  recording:
    | {
        evaluation_status?: string | null
        evaluation?: { status?: string | null } | null
      }
    | null
    | undefined,
): string | undefined {
  if (!recording) return undefined
  if (typeof recording.evaluation_status === 'string') return recording.evaluation_status
  const nested = recording.evaluation?.status
  return typeof nested === 'string' ? nested : undefined
}

export function isEvaluationStatusInProgress(status: string | null | undefined): boolean {
  return Boolean(status && ['queued', 'transcribing', 'evaluating'].includes(status))
}

export function normalizeCallRecordingList(data: unknown): Array<Record<string, unknown>> {
  return asArray<Record<string, unknown>>(data).filter((row) => typeof row === 'object')
}
