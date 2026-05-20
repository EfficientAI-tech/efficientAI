import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Layers, Save } from 'lucide-react'
import { Link } from 'react-router-dom'
import { apiClient } from '../../../lib/api'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import type {
  CallImport,
  CallImportPreviewSheet,
  CallImportSchema,
} from '../../../types/api'
import Button from '../../../components/Button'
import ParameterMappingTable, {
  buildInitialMapping,
  hydrateMappingFromPersisted,
  type SheetMappingState,
  validateMapping,
} from './ParameterMappingTable'

interface MappingPanelProps {
  callImport: CallImport
}

/**
 * MAP-stage editor on the call-import detail page.
 *
 * Lets the user pick (or change) the schema, pick a sheet when the
 * source is an Excel workbook, and edit the parameter mapping +
 * skipped columns. Submitting calls ``PATCH /call-imports/{id}/mapping``
 * which persists the mapping and transitions the batch to ``mapped``.
 *
 * Idempotent: the user can come back later and re-submit to edit the
 * mapping as long as the batch hasn't been imported yet.
 */
export default function MappingPanel({ callImport }: MappingPanelProps) {
  const queryClient = useQueryClient()
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)

  const isXlsx = callImport.source_format === 'xlsx'
  const sheets: CallImportPreviewSheet[] = callImport.available_sheets ?? []
  const usableSheets = useMemo(
    () => sheets.filter((s) => s.headers.length > 0),
    [sheets],
  )

  const [selectedSchemaId, setSelectedSchemaId] = useState<string>(
    callImport.schema_id || '',
  )
  const [selectedSheetName, setSelectedSheetName] = useState<string>(
    callImport.sheet_name ||
      (isXlsx ? usableSheets[0]?.name ?? '' : usableSheets[0]?.name ?? ''),
  )
  const [mappingState, setMappingState] = useState<SheetMappingState>({
    parameterMapping: {},
    skipped: {},
  })
  const [submitError, setSubmitError] = useState<string | null>(null)

  const { data: schemasResponse } = useQuery({
    queryKey: ['call-import-schemas', activeWorkspaceId],
    queryFn: () => apiClient.listCallImportSchemas(),
  })
  const schemas = useMemo<CallImportSchema[]>(
    () => schemasResponse?.items ?? [],
    [schemasResponse],
  )

  const selectedSchema = useMemo<CallImportSchema | null>(
    () => schemas.find((s) => s.id === selectedSchemaId) ?? null,
    [schemas, selectedSchemaId],
  )

  const selectedSheet = useMemo<CallImportPreviewSheet | null>(() => {
    if (!selectedSheetName) return usableSheets[0] ?? null
    return (
      sheets.find((s) => s.name === selectedSheetName) ??
      usableSheets[0] ??
      null
    )
  }, [sheets, usableSheets, selectedSheetName])

  // Rebuild the mapping state whenever the schema or selected sheet
  // changes. When the inputs match what the server has persisted we
  // hydrate from the persisted mapping so the user sees their previous
  // edits; otherwise we fall back to a fresh suggestion so the user
  // isn't stuck with a stale mapping pointing at the wrong schema.
  useEffect(() => {
    if (!selectedSchema || !selectedSheet) return
    const persistedMatches =
      callImport.schema_id === selectedSchema.id &&
      (callImport.sheet_name || null) === (selectedSheet.name || null)
    if (persistedMatches) {
      setMappingState(
        hydrateMappingFromPersisted(
          selectedSchema.parameters,
          selectedSheet.headers,
          callImport.parameter_mapping || {},
          callImport.skipped_columns || [],
        ),
      )
    } else {
      setMappingState(
        buildInitialMapping(selectedSchema.parameters, selectedSheet.headers),
      )
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    selectedSchema?.id,
    selectedSheet?.name,
    callImport.schema_id,
    callImport.sheet_name,
  ])

  const validation = useMemo(() => {
    if (!selectedSchema || !selectedSheet) return null
    return validateMapping(
      selectedSchema.parameters,
      selectedSheet.headers,
      mappingState,
    )
  }, [selectedSchema, selectedSheet, mappingState])

  const mappingMutation = useMutation({
    mutationFn: () => {
      if (!selectedSchema || !selectedSheet) {
        throw new Error('Pick a schema first.')
      }
      const parameterMapping: Record<string, string> = {}
      for (const [paramName, header] of Object.entries(
        mappingState.parameterMapping,
      )) {
        if (header && header.trim()) {
          parameterMapping[paramName] = header
        }
      }
      const skippedColumns = Object.keys(mappingState.skipped).filter(
        (h) => mappingState.skipped[h],
      )
      return apiClient.updateCallImportMapping(callImport.id, {
        schemaId: selectedSchema.id,
        sheetName: isXlsx ? selectedSheet.name : null,
        parameterMapping,
        skippedColumns,
      })
    },
    onSuccess: () => {
      setSubmitError(null)
      queryClient.invalidateQueries({ queryKey: ['call-import', callImport.id] })
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
    },
    onError: (err: any) => {
      setSubmitError(
        err?.response?.data?.detail ||
          err?.message ||
          'Failed to save mapping.',
      )
    },
  })

  const isAlreadyMapped = callImport.status === 'mapped'
  const canSubmit =
    !!selectedSchema &&
    !!selectedSheet &&
    !!validation?.isValid &&
    !mappingMutation.isPending

  return (
    <div className="bg-white shadow rounded-lg p-6 space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <Layers className="h-5 w-5 text-primary-600" />
          {isAlreadyMapped ? 'Edit mapping' : 'Configure mapping'}
        </h2>
        <p className="text-sm text-gray-600 mt-1">
          Pick the Input Parameter schema this batch maps against, then
          assign each schema parameter to a source column. Columns you
          don't want imported must be explicitly skipped.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Input Parameter Schema <span className="text-red-500">*</span>
          </label>
          {schemas.length === 0 ? (
            <div className="rounded-md bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800 space-y-2">
              <p>No Input Parameter schemas defined in this workspace yet.</p>
              <Link
                to="/call-imports/schemas"
                className="inline-block font-medium text-amber-900 underline hover:text-amber-700"
              >
                Create your first schema &rarr;
              </Link>
            </div>
          ) : (
            <select
              value={selectedSchemaId}
              onChange={(e) => setSelectedSchemaId(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
            >
              <option value="">Select schema</option>
              {schemas.map((schema) => (
                <option key={schema.id} value={schema.id}>
                  {schema.name} · {schema.parameters.length} params
                </option>
              ))}
            </select>
          )}
        </div>

        {isXlsx && usableSheets.length > 0 && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Worksheet <span className="text-red-500">*</span>
            </label>
            <select
              value={selectedSheetName}
              onChange={(e) => setSelectedSheetName(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
            >
              {usableSheets.map((sheet) => (
                <option key={sheet.name} value={sheet.name}>
                  {sheet.name} · {sheet.headers.length} cols · ~{sheet.row_count} rows
                </option>
              ))}
            </select>
            {sheets.length > usableSheets.length && (
              <p className="mt-1 text-xs text-gray-500">
                {sheets.length - usableSheets.length} sheet
                {sheets.length - usableSheets.length === 1 ? '' : 's'} in this
                workbook had no headers and aren't selectable.
              </p>
            )}
          </div>
        )}
      </div>

      {selectedSchema && selectedSheet ? (
        <ParameterMappingTable
          sheet={selectedSheet}
          parameters={selectedSchema.parameters}
          state={mappingState}
          onChange={setMappingState}
          disabled={mappingMutation.isPending}
        />
      ) : (
        <div className="rounded-md bg-gray-50 border border-gray-200 p-3 text-sm text-gray-600">
          {!selectedSchema
            ? 'Pick a schema above to start mapping columns.'
            : 'Pick a worksheet above to start mapping columns.'}
        </div>
      )}

      {submitError && (
        <div className="rounded-md bg-red-50 border border-red-200 p-3">
          <div className="flex items-start gap-2">
            <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
            <p className="text-sm text-red-800">{submitError}</p>
          </div>
        </div>
      )}

      <div className="flex items-center justify-end gap-3">
        <Button
          variant="primary"
          leftIcon={<Save className="h-4 w-4" />}
          onClick={() => mappingMutation.mutate()}
          isLoading={mappingMutation.isPending}
          disabled={!canSubmit}
        >
          {isAlreadyMapped ? 'Save mapping' : 'Save and continue'}
        </Button>
      </div>
    </div>
  )
}
