import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Card, CardBody, Spinner } from '@heroui/react'
import { Activity } from 'lucide-react'
import { apiClient } from '../../lib/api'

type GroupBy = 'workspace' | 'product_section' | 'model' | 'resource'

function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(value || 0)
}

function toDateInput(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function FilterField({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-gray-600">
      {label}
      {children}
    </label>
  )
}

const fieldClassName =
  'h-9 rounded-lg border border-gray-200 bg-white px-3 text-sm text-gray-900 outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-200'

export default function Usage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const today = useMemo(() => new Date(), [])
  const defaultStart = useMemo(() => {
    const d = new Date()
    d.setDate(d.getDate() - 29)
    return toDateInput(d)
  }, [])

  const start = searchParams.get('start') || defaultStart
  const end = searchParams.get('end') || toDateInput(today)
  const groupBy = (searchParams.get('group_by') as GroupBy) || 'workspace'
  const workspaceId = searchParams.get('workspace_id') || ''
  const productSection = searchParams.get('product_section') || ''
  const model = searchParams.get('model') || ''
  const resourceId = searchParams.get('resource_id') || ''

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams)
    if (!value) next.delete(key)
    else next.set(key, value)
    setSearchParams(next)
  }

  const filterParams = {
    start,
    end,
    workspace_id: workspaceId || undefined,
    product_section: productSection || undefined,
    model: model || undefined,
    resource_id: resourceId || undefined,
  }

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['org-usage', 'summary', filterParams],
    queryFn: () => apiClient.getOrgUsageSummary(filterParams),
  })

  const { data: breakdown, isLoading: breakdownLoading } = useQuery({
    queryKey: ['org-usage', 'breakdown', groupBy, filterParams],
    queryFn: () =>
      apiClient.getOrgUsageBreakdown({
        ...filterParams,
        group_by: groupBy,
        limit: 100,
      }),
  })

  const { data: filters } = useQuery({
    queryKey: ['org-usage', 'filters', start, end],
    queryFn: () => apiClient.getOrgUsageFilters({ start, end }),
  })

  const totals = summary?.totals
  const rows = breakdown?.rows || []

  const dimensionLabel = (row: (typeof rows)[number]): string => {
    if (groupBy === 'workspace') return row.workspace_name || 'Unknown'
    if (groupBy === 'product_section')
      return row.product_section_label || row.product_section || '—'
    if (groupBy === 'model') return row.model || '—'
    return row.resource_label || row.resource_id || 'Unscoped'
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Activity className="h-6 w-6 text-indigo-600" />
            Usage
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Organization-wide LLM tokens and calls. Filter by workspace, product
            section, model, or evaluation.
          </p>
        </div>
        {summary?.last_updated_at && (
          <p className="text-xs text-gray-400 whitespace-nowrap">
            Updated {new Date(summary.last_updated_at).toLocaleString()}
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Input tokens" value={totals?.prompt_tokens} loading={summaryLoading} />
        <StatCard label="Output tokens" value={totals?.completion_tokens} loading={summaryLoading} />
        <StatCard label="Total tokens" value={totals?.total_tokens} loading={summaryLoading} />
        <StatCard label="LLM calls" value={totals?.call_count} loading={summaryLoading} />
      </div>

      {(totals?.cache_read_tokens || totals?.cache_creation_tokens || totals?.reasoning_tokens) ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <StatCard label="Cache read" value={totals?.cache_read_tokens} loading={summaryLoading} />
          <StatCard label="Cache write" value={totals?.cache_creation_tokens} loading={summaryLoading} />
          <StatCard label="Reasoning" value={totals?.reasoning_tokens} loading={summaryLoading} />
        </div>
      ) : null}

      <Card shadow="sm">
        <CardBody className="gap-4 p-4">
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <FilterField label="Start">
              <input
                type="date"
                className={fieldClassName}
                value={start}
                onChange={(e) => setParam('start', e.target.value)}
              />
            </FilterField>
            <FilterField label="End">
              <input
                type="date"
                className={fieldClassName}
                value={end}
                onChange={(e) => setParam('end', e.target.value)}
              />
            </FilterField>
            <FilterField label="Workspace">
              <select
                className={fieldClassName}
                value={workspaceId}
                onChange={(e) => setParam('workspace_id', e.target.value)}
              >
                <option value="">All workspaces</option>
                {(filters?.workspaces || []).map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </FilterField>
            <FilterField label="Product section">
              <select
                className={fieldClassName}
                value={productSection}
                onChange={(e) => setParam('product_section', e.target.value)}
              >
                <option value="">All sections</option>
                {(filters?.product_sections || []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </FilterField>
            <FilterField label="Model">
              <select
                className={fieldClassName}
                value={model}
                onChange={(e) => setParam('model', e.target.value)}
              >
                <option value="">All models</option>
                {(filters?.models || []).map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </FilterField>
            <FilterField label="Group by">
              <select
                className={fieldClassName}
                value={groupBy}
                onChange={(e) => setParam('group_by', e.target.value)}
              >
                <option value="workspace">Workspace</option>
                <option value="product_section">Product section</option>
                <option value="model">Model</option>
                <option value="resource">Evaluation / resource</option>
              </select>
            </FilterField>
          </div>
        </CardBody>
      </Card>

      <Card shadow="sm">
        <CardBody className="p-0 overflow-x-auto">
          {breakdownLoading ? (
            <div className="flex justify-center py-12">
              <Spinner />
            </div>
          ) : rows.length === 0 ? (
            <div className="py-12 text-center text-sm text-gray-500">
              No usage in this period. Run evaluations or playground calls, then
              refresh in a minute.
            </div>
          ) : (
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-3 font-semibold">
                    {groupBy === 'workspace'
                      ? 'Workspace'
                      : groupBy === 'product_section'
                        ? 'Section'
                        : groupBy === 'model'
                          ? 'Model'
                          : 'Resource'}
                  </th>
                  <th className="px-4 py-3 font-semibold text-right">Calls</th>
                  <th className="px-4 py-3 font-semibold text-right">Input</th>
                  <th className="px-4 py-3 font-semibold text-right">Output</th>
                  <th className="px-4 py-3 font-semibold text-right">Total</th>
                  <th className="px-4 py-3 font-semibold text-right">Cache read</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {rows.map((row, idx) => (
                  <tr key={idx} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-gray-900">{dimensionLabel(row)}</td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatNumber(row.call_count)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatNumber(row.prompt_tokens)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatNumber(row.completion_tokens)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums font-medium">
                      {formatNumber(row.total_tokens)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-gray-500">
                      {formatNumber(row.cache_read_tokens)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardBody>
      </Card>
    </div>
  )
}

function StatCard({
  label,
  value,
  loading,
}: {
  label: string
  value?: number
  loading?: boolean
}) {
  return (
    <Card shadow="sm">
      <CardBody className="p-4">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">
          {label}
        </p>
        <p className="mt-1 text-2xl font-semibold text-gray-900 tabular-nums">
          {loading ? '—' : formatNumber(value || 0)}
        </p>
      </CardBody>
    </Card>
  )
}
