import type { CallImportRow } from '../../../types/api'

export function basenameFromS3Key(key: string | null | undefined): string | null {
  if (!key) return null
  const parts = key.split('/')
  const name = parts[parts.length - 1]?.trim()
  return name || null
}

export function getCallImportBatchLabel(importBatch: {
  original_filename?: string | null
  name?: string | null
  id?: string
}): string {
  return (
    importBatch.original_filename?.trim() ||
    importBatch.name?.trim() ||
    importBatch.id?.slice(0, 8) ||
    'Unnamed import'
  )
}

export function getCallImportRowLabel(row: Pick<CallImportRow, 'recording_s3_key' | 'conversation_id' | 'row_index' | 'id'>): string {
  const filename = basenameFromS3Key(row.recording_s3_key)
  if (filename) return filename
  if (row.conversation_id?.trim()) return row.conversation_id.trim()
  return `Import row ${row.row_index ?? row.id.slice(0, 8)}`
}

export function getCallImportRowSubtitle(row: Pick<CallImportRow, 'row_index' | 'conversation_id' | 'id'>): string {
  if (row.conversation_id?.trim()) {
    return `Row ${row.row_index} · ${row.conversation_id}`
  }
  return `Row ${row.row_index}`
}

export function getPlaygroundRecordingLabel(recording: {
  display_name?: string | null
  call_short_id: string
}): string {
  return recording.display_name?.trim() || recording.call_short_id
}

export function getObservabilityCallLabel(call: {
  display_name?: string | null
  agent?: { name?: string | null } | null
  provider_platform?: string | null
  call_short_id: string
}): string {
  return (
    call.display_name?.trim() ||
    call.agent?.name?.trim() ||
    (call.provider_platform ? `${call.provider_platform} call` : null) ||
    call.call_short_id
  )
}

export function getSimulatedResultLabel(item: {
  name?: string | null
  result_id?: string | null
  id: string
}): string {
  return item.name?.trim() || item.result_id?.trim() || item.id.slice(0, 8)
}

export function getSimulatedResultSubtitle(item: {
  result_id?: string | null
  id: string
}): string | null {
  if (item.result_id && item.result_id !== item.id) return item.result_id
  return null
}
