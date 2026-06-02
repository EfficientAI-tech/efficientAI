import { useMemo } from 'react'
import { FileText } from 'lucide-react'
import type {
  CallImportPreviewSheet,
  CallImportSchemaParameter,
} from '../../../types/api'

/**
 * Per-sheet mapping state.
 *
 * ``parameterMapping`` is keyed by schema parameter name (NOT by CSV
 * header) so the dropdown logic stays symmetrical with the backend
 * wire format. ``skipped`` is the explicit set of CSV headers the user
 * has acknowledged dropping; every CSV header must end up either in
 * ``parameterMapping`` (as a value) or in ``skipped`` before the
 * caller's submit button is enabled.
 */
export interface SheetMappingState {
  parameterMapping: Record<string, string>
  skipped: Record<string, boolean>
}

export interface SheetValidation {
  /** Required schema params with no CSV header assigned. */
  missingRequired: string[]
  /** Same CSV header assigned to more than one parameter. */
  duplicateAssignments: string[]
  /** Headers that are neither mapped to a parameter nor explicitly skipped. */
  unhandledHeaders: string[]
  isValid: boolean
}

const NOT_USED = '__not_used__'

export function normalizeHeader(header: string): string {
  return header.toLowerCase().trim().replace(/[\s_\-.]+/g, '')
}

// Heuristic header suggestion for a single schema parameter. Keeps the
// upload flow "explicit by default" — if no clear match is found we
// leave the dropdown blank so the user makes a conscious choice. We
// only auto-pick when there's exactly one plausible header.
export function suggestHeaderForParameter(
  param: CallImportSchemaParameter,
  availableHeaders: string[],
): string | null {
  const name = normalizeHeader(param.name)
  const explicitMatch = availableHeaders.find(
    (h) => normalizeHeader(h) === name,
  )
  if (explicitMatch) return explicitMatch
  if (param.type === 'conversation_id') {
    const candidates = availableHeaders.filter((h) => {
      const norm = normalizeHeader(h)
      return (
        norm === 'conversationid' ||
        norm === 'externalcallid' ||
        norm === 'callid' ||
        norm === 'callsid' ||
        norm === 'sid' ||
        norm === 'calluuid' ||
        norm === 'uuid'
      )
    })
    if (candidates.length === 1) return candidates[0]
  }
  if (param.type === 'recording_url') {
    const candidates = availableHeaders.filter((h) => {
      const norm = normalizeHeader(h)
      return (
        norm === 'recordingurl' ||
        norm === 'recordinglink' ||
        norm === 'recording'
      )
    })
    if (candidates.length === 1) return candidates[0]
  }
  if (param.type === 'recording_date') {
    const candidates = availableHeaders.filter((h) => {
      const norm = normalizeHeader(h)
      return (
        norm === 'recordingdate' ||
        norm === 'calldate' ||
        norm === 'dateofrecording' ||
        norm === 'date'
      )
    })
    if (candidates.length === 1) return candidates[0]
  }
  if (param.type === 'transcript') {
    const candidates = availableHeaders.filter((h) => {
      const norm = normalizeHeader(h)
      return norm.includes('transcript') || norm.includes('transcription')
    })
    if (candidates.length === 1) return candidates[0]
  }
  return null
}

/**
 * Build an initial per-sheet mapping. Auto-binds parameters whose
 * heuristic matches a single header, and defaults every remaining
 * header to "skipped" so the user can submit immediately on the happy
 * path; they only have to flip a checkbox when they actually want to
 * add a column.
 */
export function buildInitialMapping(
  parameters: CallImportSchemaParameter[],
  headers: string[],
): SheetMappingState {
  const parameterMapping: Record<string, string> = {}
  const used = new Set<string>()
  for (const param of parameters) {
    const suggestion = suggestHeaderForParameter(param, headers)
    if (suggestion && !used.has(suggestion)) {
      parameterMapping[param.name] = suggestion
      used.add(suggestion)
    } else {
      parameterMapping[param.name] = ''
    }
  }
  const skipped: Record<string, boolean> = {}
  for (const h of headers) {
    if (!used.has(h)) skipped[h] = true
  }
  return { parameterMapping, skipped }
}

/**
 * Build mapping state from values the server has already persisted
 * (parameter_mapping + skipped_columns). Used by the MAP panel on the
 * detail page when the user is editing an existing mapping.
 */
export function hydrateMappingFromPersisted(
  parameters: CallImportSchemaParameter[],
  headers: string[],
  persistedMapping: Record<string, string>,
  persistedSkipped: string[],
): SheetMappingState {
  const parameterMapping: Record<string, string> = {}
  for (const param of parameters) {
    const header = persistedMapping[param.name]
    parameterMapping[param.name] = header && headers.includes(header) ? header : ''
  }
  const used = new Set(
    Object.values(parameterMapping).filter((v) => !!v) as string[],
  )
  const skipped: Record<string, boolean> = {}
  const persistedSkippedSet = new Set(persistedSkipped)
  for (const h of headers) {
    if (used.has(h)) continue
    skipped[h] = persistedSkippedSet.has(h)
  }
  return { parameterMapping, skipped }
}

export function validateMapping(
  parameters: CallImportSchemaParameter[],
  headers: string[],
  state: SheetMappingState,
): SheetValidation {
  const missingRequired: string[] = []
  const usageCount: Record<string, number> = {}
  for (const param of parameters) {
    const header = (state.parameterMapping[param.name] || '').trim()
    if (param.is_required && !header) {
      missingRequired.push(param.name)
    }
    if (header) {
      usageCount[header] = (usageCount[header] || 0) + 1
    }
  }
  const duplicateAssignments = Object.entries(usageCount)
    .filter(([, count]) => count > 1)
    .map(([header]) => header)

  const mappedSet = new Set(
    Object.values(state.parameterMapping).filter((v) => v),
  )
  const unhandledHeaders = headers.filter(
    (h) => !mappedSet.has(h) && !state.skipped[h],
  )

  return {
    missingRequired,
    duplicateAssignments,
    unhandledHeaders,
    isValid:
      missingRequired.length === 0 &&
      duplicateAssignments.length === 0 &&
      unhandledHeaders.length === 0,
  }
}

interface ParameterMappingTableProps {
  sheet: CallImportPreviewSheet
  parameters: CallImportSchemaParameter[]
  state: SheetMappingState
  onChange: (next: SheetMappingState) => void
  disabled?: boolean
}

/**
 * The two-pane table used inside both the upload modal (legacy flow)
 * and the MAP panel on the detail page (staged flow). Left pane: one
 * row per schema parameter with a "source column" dropdown. Right
 * pane: every CSV header that wasn't picked above, each with a
 * "Skip" checkbox so nothing silently drops.
 */
export default function ParameterMappingTable({
  sheet,
  parameters,
  state,
  onChange,
  disabled,
}: ParameterMappingTableProps) {
  const headers = sheet.headers
  const validation = validateMapping(parameters, headers, state)
  const mappedHeaders = useMemo(
    () => new Set(Object.values(state.parameterMapping).filter((v) => v)),
    [state.parameterMapping],
  )

  const setParameterHeader = (paramName: string, header: string) => {
    onChange({
      ...state,
      parameterMapping: {
        ...state.parameterMapping,
        [paramName]: header === NOT_USED ? '' : header,
      },
      skipped:
        header === NOT_USED
          ? state.skipped
          : { ...state.skipped, [header]: false },
    })
  }

  const setHeaderSkipped = (header: string, skipped: boolean) => {
    onChange({
      ...state,
      skipped: { ...state.skipped, [header]: skipped },
    })
  }

  return (
    <div className="space-y-4">
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <div className="grid grid-cols-[1fr_1fr] bg-gray-50 px-3 py-2 text-xs font-medium text-gray-600 border-b border-gray-200">
          <div>Schema parameter</div>
          <div>Source column</div>
        </div>
        <div className="max-h-[420px] overflow-y-auto divide-y divide-gray-100">
          {parameters.length === 0 ? (
            <p className="px-3 py-3 text-xs text-gray-500">
              The selected schema has no parameters defined.
            </p>
          ) : (
            parameters.map((param) => {
              const selected =
                state.parameterMapping[param.name] || NOT_USED
              const isLocked = param.type === 'conversation_id'
              return (
                <div
                  key={param.name}
                  className="grid grid-cols-[1fr_1fr] gap-2 items-start px-3 py-2"
                >
                  <div className="text-sm text-gray-800 truncate flex items-start gap-1.5 pt-1.5">
                    <FileText className="h-3.5 w-3.5 text-gray-400 flex-shrink-0 mt-0.5" />
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate font-medium">{param.name}</span>
                        {param.is_required && (
                          <span className="text-[10px] uppercase tracking-wide text-red-600">
                            required
                          </span>
                        )}
                        {isLocked && (
                          <span className="text-[10px] uppercase tracking-wide text-primary-600">
                            id
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-gray-500 mt-0.5 truncate">
                        {param.type}
                        {param.description ? ` · ${param.description}` : ''}
                      </div>
                    </div>
                  </div>
                  <div>
                    <select
                      value={selected}
                      onChange={(e) =>
                        setParameterHeader(param.name, e.target.value)
                      }
                      disabled={disabled}
                      className="w-full px-2 py-1.5 border border-gray-300 rounded text-sm focus:ring-2 focus:ring-primary-500 disabled:opacity-60"
                    >
                      <option value={NOT_USED}>
                        {param.is_required
                          ? '— Select source column —'
                          : '— Not used —'}
                      </option>
                      {headers.map((h) => (
                        <option key={h} value={h}>
                          {h}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>

      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <div className="bg-gray-50 px-3 py-2 text-xs font-medium text-gray-600 border-b border-gray-200">
          Unmapped source columns
        </div>
        <div className="max-h-[240px] overflow-y-auto divide-y divide-gray-100">
          {headers.filter((h) => !mappedHeaders.has(h)).length === 0 ? (
            <p className="px-3 py-3 text-xs text-gray-500">
              Every source column has been mapped to a parameter.
            </p>
          ) : (
            headers
              .filter((h) => !mappedHeaders.has(h))
              .map((header) => {
                const isSkipped = !!state.skipped[header]
                return (
                  <label
                    key={header}
                    className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-gray-50"
                  >
                    <input
                      type="checkbox"
                      checked={isSkipped}
                      onChange={(e) =>
                        setHeaderSkipped(header, e.target.checked)
                      }
                      disabled={disabled}
                      className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                    />
                    <span className="text-sm text-gray-800 truncate">
                      {header}
                    </span>
                    <span className="text-xs text-gray-500 ml-auto">
                      {isSkipped ? 'Will be skipped' : 'Needs decision'}
                    </span>
                  </label>
                )
              })
          )}
        </div>
      </div>

      <div className="space-y-1">
        {validation.missingRequired.length > 0 && (
          <p className="text-xs text-red-600">
            Required parameter
            {validation.missingRequired.length > 1 ? 's' : ''} not mapped:{' '}
            <strong>{validation.missingRequired.join(', ')}</strong>.
          </p>
        )}
        {validation.duplicateAssignments.length > 0 && (
          <p className="text-xs text-red-600">
            Source columns assigned to multiple parameters:{' '}
            <strong>{validation.duplicateAssignments.join(', ')}</strong>.
          </p>
        )}
        {validation.unhandledHeaders.length > 0 && (
          <p className="text-xs text-red-600">
            Decide what to do with{' '}
            <strong>{validation.unhandledHeaders.join(', ')}</strong> — map
            to a parameter above or tick "Skip".
          </p>
        )}
      </div>
    </div>
  )
}
