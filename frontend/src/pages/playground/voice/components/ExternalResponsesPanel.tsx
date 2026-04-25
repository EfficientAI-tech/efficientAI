import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Loader2, Users } from 'lucide-react'
import ProviderLogo, { getProviderInfo } from '../../../../components/shared/ProviderLogo'
import { apiClient } from '../../../../lib/api'
import {
  BlindTestResponseRow,
  BlindTestShareDetail,
  TTSComparison,
} from '../types'

interface ExternalResponsesPanelProps {
  comparison: TTSComparison
}

export default function ExternalResponsesPanel({ comparison }: ExternalResponsesPanelProps) {
  const [expanded, setExpanded] = useState(false)

  const { data: share, isLoading: shareLoading } = useQuery<BlindTestShareDetail | null>({
    queryKey: ['blind-test-share', comparison.id],
    queryFn: async () => {
      try {
        return await apiClient.getBlindTestShare(comparison.id)
      } catch (err: any) {
        if (err?.response?.status === 404) return null
        throw err
      }
    },
    enabled: !!comparison.id,
    refetchInterval: 15000,
  })

  const { data: responseData, isLoading: responsesLoading } = useQuery<{
    items: BlindTestResponseRow[]
    total: number
  }>({
    queryKey: ['blind-test-responses', share?.id],
    queryFn: () => apiClient.listBlindTestResponses(share!.id),
    enabled: !!share?.id && expanded,
  })

  if (shareLoading) {
    return (
      <div className="bg-white rounded-xl shadow-lg p-6 flex items-center gap-2 text-sm text-gray-500">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading external responses...
      </div>
    )
  }

  if (!share) {
    return null
  }

  const aggregates = share.aggregates
  const responseCount = share.response_count ?? aggregates?.response_count ?? 0

  if (responseCount === 0) {
    return (
      <div className="bg-white rounded-xl shadow-lg p-6">
        <h3 className="font-semibold text-gray-900 mb-1 flex items-center gap-2">
          <Users className="w-5 h-5 text-gray-600" />
          External Responses
        </h3>
        <p className="text-sm text-gray-500">
          No external responses yet. Share the link from the Create Blind Test button above to start
          collecting feedback.
        </p>
      </div>
    )
  }

  const providerALabel = getProviderInfo(comparison.provider_a).label
  const providerBLabel = getProviderInfo(comparison.provider_b || '').label

  return (
    <div className="bg-white rounded-xl shadow-lg p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <Users className="w-5 h-5 text-gray-600" />
          External Responses
          <span className="ml-2 px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-600">
            {responseCount}
          </span>
        </h3>
        <span
          className={`text-xs px-2 py-0.5 rounded-full ${
            share.status === 'open' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
          }`}
        >
          {share.status === 'open' ? 'Accepting responses' : 'Closed'}
        </span>
      </div>

      {aggregates && (
        <div className="p-4 bg-gradient-to-r from-amber-50 to-orange-50 rounded-xl border border-amber-200">
          <div className="flex items-center justify-around">
            <div className="text-center flex flex-col items-center gap-1">
              <ProviderLogo provider={comparison.provider_a} size="sm" />
              <p className="text-xs text-gray-500">{providerALabel}</p>
              <p className="text-2xl font-bold text-blue-600">{aggregates.a_pct}%</p>
              <p className="text-xs text-gray-400">{aggregates.a_wins} preferred</p>
            </div>
            <span className="text-gray-300 text-xl">vs</span>
            <div className="text-center flex flex-col items-center gap-1">
              <ProviderLogo provider={comparison.provider_b || ''} size="sm" />
              <p className="text-xs text-gray-500">{providerBLabel}</p>
              <p className="text-2xl font-bold text-purple-600">{aggregates.b_pct}%</p>
              <p className="text-xs text-gray-400">{aggregates.b_wins} preferred</p>
            </div>
          </div>
        </div>
      )}

      {aggregates && Object.keys(aggregates.metrics).length > 0 && (
        <div className="overflow-hidden rounded-lg border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr className="text-left text-xs uppercase tracking-wide text-gray-500">
                <th className="px-3 py-2">Metric</th>
                <th className="px-3 py-2 text-right">{providerALabel} (avg)</th>
                <th className="px-3 py-2 text-right">{providerBLabel} (avg)</th>
                <th className="px-3 py-2 text-right">Ratings</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {Object.entries(aggregates.metrics).map(([key, m]) => (
                <tr key={key}>
                  <td className="px-3 py-2 font-medium text-gray-700">{m.label}</td>
                  <td className="px-3 py-2 text-right text-blue-600 font-semibold">
                    {m.avg_a !== null ? m.avg_a.toFixed(2) : '—'}
                    {m.scale ? <span className="text-gray-400 text-xs">/{m.scale}</span> : null}
                  </td>
                  <td className="px-3 py-2 text-right text-purple-600 font-semibold">
                    {m.avg_b !== null ? m.avg_b.toFixed(2) : '—'}
                    {m.scale ? <span className="text-gray-400 text-xs">/{m.scale}</span> : null}
                  </td>
                  <td className="px-3 py-2 text-right text-xs text-gray-500">
                    {m.samples_a} / {m.samples_b}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <button
        onClick={() => setExpanded(prev => !prev)}
        className="flex items-center gap-1 text-sm text-gray-600 hover:text-gray-900"
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4" />
        ) : (
          <ChevronRight className="w-4 h-4" />
        )}
        {expanded ? 'Hide' : 'Show'} individual responses
      </button>

      {expanded && (
        <div className="space-y-3">
          {responsesLoading && (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading responses...
            </div>
          )}
          {responseData?.items.map(row => (
            <div key={row.id} className="rounded-lg border border-gray-200 p-3">
              <div className="flex items-center justify-between text-sm mb-2">
                <div>
                  <p className="font-medium text-gray-800">{row.rater_name}</p>
                  <p className="text-xs text-gray-500">{row.rater_email}</p>
                </div>
                <p className="text-xs text-gray-400">
                  {row.submitted_at ? new Date(row.submitted_at).toLocaleString() : ''}
                </p>
              </div>
              <div className="space-y-1.5">
                {row.responses.map((entry, idx) => (
                  <div key={idx} className="text-xs text-gray-600 flex flex-wrap gap-x-3 gap-y-1">
                    <span className="font-mono text-gray-400">#{entry.sample_index}</span>
                    <span>
                      Preferred:{' '}
                      <strong
                        className={
                          entry.preferred === 'A' ? 'text-blue-600' : 'text-purple-600'
                        }
                      >
                        {entry.preferred === 'A' ? providerALabel : providerBLabel}
                      </strong>
                    </span>
                    {Object.entries(entry.ratings_a || {}).map(([k, v]) => (
                      <span key={`a-${k}`}>
                        {k}: <span className="text-blue-600">{v}</span> /{' '}
                        <span className="text-purple-600">{entry.ratings_b?.[k] ?? '—'}</span>
                      </span>
                    ))}
                    {entry.comment && (
                      <span className="text-gray-700 italic">“{entry.comment}”</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
