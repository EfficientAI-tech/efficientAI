import { useMemo } from 'react'
import { Loader2, ArrowUpDown } from 'lucide-react'
import { BarChart, Bar, Cell, LabelList, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts'
import ProviderLogo, { getProviderInfo } from '../../../../components/shared/ProviderLogo'
import { useVoicePlayground } from '../context'
import { BENCHMARK_METRIC_OPTIONS, AnalyticsSortKey, BenchmarkMetricKey } from '../types'

function providerBenchmarkColor(provider: string): string {
  const key = provider.toLowerCase()
  const palette: Record<string, string> = {
    openai: '#10b981',
    elevenlabs: '#8b5cf6',
    cartesia: '#3b82f6',
    deepgram: '#f59e0b',
    voicemaker: '#ec4899',
    google: '#ef4444',
  }
  return palette[key] || '#6b7280'
}

function AnalyticsMetricCell({ value, max, unit, higherIsBetter = true }: {
  value: number | null; max?: number; unit?: string; higherIsBetter?: boolean
}) {
  if (value == null) return <span className="text-gray-300">—</span>

  let colorClass = 'text-gray-700'
  if (max != null) {
    const ratio = value / max
    if (higherIsBetter) {
      if (ratio >= 0.75) colorClass = 'text-green-600 font-semibold'
      else if (ratio >= 0.5) colorClass = 'text-yellow-600'
      else colorClass = 'text-red-500'
    } else {
      if (ratio <= 0.25) colorClass = 'text-green-600 font-semibold'
      else if (ratio <= 0.5) colorClass = 'text-yellow-600'
      else colorClass = 'text-red-500'
    }
  } else if (!higherIsBetter) {
    if (value <= 300) colorClass = 'text-green-600 font-semibold'
    else if (value <= 600) colorClass = 'text-yellow-600'
    else colorClass = 'text-red-500'
  }

  const formatted = unit === 'ms'
    ? `${Math.round(value)}ms`
    : unit === '%'
    ? `${(value * 100).toFixed(1)}%`
    : value.toFixed(2)

  return <span className={colorClass}>{formatted}</span>
}

export default function AnalyticsPanel() {
  const {
    analyticsData,
    analyticsLoading,
    analyticsSortKey,
    toggleAnalyticsSort,
    sortedAnalytics,
    selectedBenchmarkMetric,
    setSelectedBenchmarkMetric,
    benchmarkTopN,
    setBenchmarkTopN,
  } = useVoicePlayground()

  const analyticsOverview = useMemo(() => {
    if (analyticsData.length === 0) {
      return {
        totalVoices: 0,
        totalSamples: 0,
        avgMos: null as number | null,
        avgTtfb: null as number | null,
        avgLatency: null as number | null,
      }
    }
    const totalSamples = analyticsData.reduce((sum, row) => sum + (row.sample_count || 0), 0)
    const weightedMos = analyticsData.reduce(
      (sum, row) => sum + (row.avg_mos || 0) * (row.sample_count || 0),
      0
    )
    const weightedTtfb = analyticsData.reduce(
      (sum, row) => sum + (row.avg_ttfb_ms || 0) * (row.sample_count || 0),
      0
    )
    const weightedLatency = analyticsData.reduce(
      (sum, row) => sum + (row.avg_latency_ms || 0) * (row.sample_count || 0),
      0
    )
    const mosWeight = analyticsData.reduce(
      (sum, row) => sum + (row.avg_mos != null ? row.sample_count || 0 : 0),
      0
    )
    const ttfbWeight = analyticsData.reduce(
      (sum, row) => sum + (row.avg_ttfb_ms != null ? row.sample_count || 0 : 0),
      0
    )
    const latencyWeight = analyticsData.reduce(
      (sum, row) => sum + (row.avg_latency_ms != null ? row.sample_count || 0 : 0),
      0
    )
    return {
      totalVoices: analyticsData.length,
      totalSamples,
      avgMos: mosWeight > 0 ? Number((weightedMos / mosWeight).toFixed(2)) : null,
      avgTtfb: ttfbWeight > 0 ? Number((weightedTtfb / ttfbWeight).toFixed(0)) : null,
      avgLatency: latencyWeight > 0 ? Number((weightedLatency / latencyWeight).toFixed(0)) : null,
    }
  }, [analyticsData])

  const benchmarkRows = useMemo(() => {
    return analyticsData.map((row) => ({
      id: `${row.provider}-${row.model}-${row.voice_id}`,
      provider: row.provider,
      model: row.model,
      voice_name: row.voice_name,
      sample_count: row.sample_count,
      avg_mos: row.avg_mos,
      avg_valence: row.avg_valence,
      avg_arousal: row.avg_arousal,
      avg_prosody: row.avg_prosody,
      avg_ttfb_ms: row.avg_ttfb_ms,
      avg_latency_ms: row.avg_latency_ms,
      avg_wer: row.avg_wer,
      avg_cer: row.avg_cer,
      label: `${row.voice_name} • ${getProviderInfo(row.provider).label} • ${row.model}`,
      short_label:
        row.voice_name.length > 16 ? `${row.voice_name.slice(0, 16)}...` : row.voice_name,
    }))
  }, [analyticsData])

  const selectedBenchmarkConfig = useMemo(
    () =>
      BENCHMARK_METRIC_OPTIONS.find((opt) => opt.key === selectedBenchmarkMetric) ||
      BENCHMARK_METRIC_OPTIONS[0],
    [selectedBenchmarkMetric]
  )

  const benchmarkChartData = useMemo(() => {
    const { key, higherIsBetter, unit } = selectedBenchmarkConfig
    const sorted = [...benchmarkRows]
      .filter((r) => r[key] != null)
      .sort((a, b) => {
        const aVal = a[key] as number
        const bVal = b[key] as number
        return higherIsBetter ? bVal - aVal : aVal - bVal
      })
      .slice(0, benchmarkTopN)

    return sorted.map((r) => {
      const rawValue = r[key] as number
      return {
        id: r.id,
        provider: r.provider,
        label: r.label,
        shortLabel: r.short_label,
        model: r.model,
        voice: r.voice_name,
        sampleCount: r.sample_count,
        value: unit === 'ms' ? Number(rawValue.toFixed(0)) : Number(rawValue.toFixed(2)),
        valueLabel: unit === 'ms' ? `${Math.round(rawValue)}ms` : rawValue.toFixed(2),
      }
    })
  }, [benchmarkRows, selectedBenchmarkConfig, benchmarkTopN])

  // Compute column maxes for color coding
  const maxMos = useMemo(() => Math.max(...analyticsData.map(r => r.avg_mos ?? 0), 0.01), [analyticsData])
  const maxTtfb = useMemo(() => Math.max(...analyticsData.map(r => r.avg_ttfb_ms ?? 0), 0.01), [analyticsData])
  const maxLatency = useMemo(() => Math.max(...analyticsData.map(r => r.avg_latency_ms ?? 0), 0.01), [analyticsData])

  if (analyticsLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-gray-500">
        <Loader2 className="w-6 h-6 animate-spin mr-2" />
        Loading analytics...
      </div>
    )
  }

  if (analyticsData.length === 0) {
    return (
      <div className="bg-white rounded-xl shadow-lg p-8 text-center text-gray-500">
        <p>No analytics data yet. Run some TTS comparisons first.</p>
      </div>
    )
  }

  const renderSortableHeader = (label: string, key: AnalyticsSortKey) => (
    <th
      onClick={() => toggleAnalyticsSort(key)}
      className="px-3 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider cursor-pointer hover:text-gray-700 select-none"
    >
      <span className="inline-flex items-center gap-1">
        {label}
        <ArrowUpDown
          className={`w-3 h-3 ${analyticsSortKey === key ? 'text-primary-600' : 'text-gray-300'}`}
        />
      </span>
    </th>
  )

  return (
    <div className="space-y-6">
      {/* Overview Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div className="bg-white rounded-lg shadow p-4 text-center">
          <p className="text-2xl font-bold text-gray-900">{analyticsOverview.totalVoices}</p>
          <p className="text-xs text-gray-500">Unique Voices</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4 text-center">
          <p className="text-2xl font-bold text-gray-900">{analyticsOverview.totalSamples}</p>
          <p className="text-xs text-gray-500">Total Samples</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4 text-center">
          <p className="text-2xl font-bold text-primary-600">
            {analyticsOverview.avgMos ?? '-'}
          </p>
          <p className="text-xs text-gray-500">Avg MOS</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4 text-center">
          <p className="text-2xl font-bold text-amber-600">
            {analyticsOverview.avgTtfb ? `${analyticsOverview.avgTtfb}ms` : '-'}
          </p>
          <p className="text-xs text-gray-500">Avg TTFB</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4 text-center">
          <p className="text-2xl font-bold text-blue-600">
            {analyticsOverview.avgLatency ? `${analyticsOverview.avgLatency}ms` : '-'}
          </p>
          <p className="text-xs text-gray-500">Avg Latency</p>
        </div>
      </div>

      {/* Benchmark Chart + Ranking */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-white rounded-xl shadow-lg p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-gray-900">Voice Benchmark</h3>
            <div className="flex items-center gap-3">
              <select
                value={selectedBenchmarkMetric}
                onChange={(e) => setSelectedBenchmarkMetric(e.target.value as BenchmarkMetricKey)}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
              >
                {BENCHMARK_METRIC_OPTIONS.map((opt) => (
                  <option key={opt.key} value={opt.key}>
                    {opt.title}
                  </option>
                ))}
              </select>
              <select
                value={benchmarkTopN}
                onChange={(e) => setBenchmarkTopN(Number(e.target.value))}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
              >
                {[5, 10, 15, 20].map((n) => (
                  <option key={n} value={n}>
                    Top {n}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <p className="text-xs text-gray-500 mb-4">{selectedBenchmarkConfig.subtitle}</p>

          {benchmarkChartData.length > 0 ? (
            <div className="overflow-x-auto">
              <BarChart
                width={Math.max(600, benchmarkChartData.length * 80)}
                height={350}
                data={benchmarkChartData}
                margin={{ top: 20, right: 30, left: 20, bottom: 60 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis
                  dataKey="shortLabel"
                  angle={-45}
                  textAnchor="end"
                  tick={{ fontSize: 10, fill: '#6b7280' }}
                  height={80}
                />
                <YAxis tick={{ fontSize: 10, fill: '#6b7280' }} />
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null
                    const data = payload[0].payload
                    return (
                      <div className="bg-white shadow-lg rounded-lg p-3 border border-gray-200">
                        <p className="font-medium text-gray-900">{data.voice}</p>
                        <p className="text-xs text-gray-500">
                          {getProviderInfo(data.provider).label} • {data.model}
                        </p>
                        <p className="text-sm font-semibold mt-1">
                          {selectedBenchmarkConfig.title}: {data.valueLabel}
                        </p>
                        <p className="text-xs text-gray-400">{data.sampleCount} samples</p>
                      </div>
                    )
                  }}
                />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {benchmarkChartData.map((entry) => (
                    <Cell key={entry.id} fill={providerBenchmarkColor(entry.provider)} />
                  ))}
                  <LabelList
                    dataKey="valueLabel"
                    position="top"
                    fill="#374151"
                    fontSize={10}
                  />
                </Bar>
              </BarChart>
            </div>
          ) : (
            <p className="text-center text-gray-500 py-8">
              No data available for this metric.
            </p>
          )}
        </div>

        {/* Ranking sidebar */}
        <div className="bg-gray-50 rounded-xl border border-gray-100 p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Ranking</h3>
          <div className="space-y-2 max-h-[360px] overflow-y-auto pr-1">
            {benchmarkChartData.map((row, idx) => (
              <div key={row.id} className="bg-white rounded-lg border border-gray-100 p-2.5 flex items-center gap-2">
                <span className="w-6 h-6 rounded-full bg-gray-900 text-white text-[10px] font-bold flex items-center justify-center">
                  {idx + 1}
                </span>
                <ProviderLogo provider={row.provider} size="sm" />
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-gray-800 truncate">{row.voice}</p>
                  <p className="text-[10px] text-gray-500 truncate">{getProviderInfo(row.provider).label} • {row.model}</p>
                </div>
                <span className="text-xs font-semibold text-gray-800 bg-gray-100 px-2 py-1 rounded-md">
                  {row.valueLabel}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Analytics Table */}
      <div className="bg-white rounded-xl shadow-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200">
          <h3 className="font-semibold text-gray-900">Detailed Analytics</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                {renderSortableHeader('Provider', 'provider')}
                {renderSortableHeader('Model', 'model')}
                {renderSortableHeader('Voice', 'voice_name')}
                {renderSortableHeader('Samples', 'sample_count')}
                {renderSortableHeader('MOS', 'avg_mos')}
                {renderSortableHeader('Valence', 'avg_valence')}
                {renderSortableHeader('Arousal', 'avg_arousal')}
                {renderSortableHeader('Prosody', 'avg_prosody')}
                {renderSortableHeader('TTFB', 'avg_ttfb_ms')}
                {renderSortableHeader('Latency', 'avg_latency_ms')}
                {renderSortableHeader('WER', 'avg_wer')}
                {renderSortableHeader('CER', 'avg_cer')}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {sortedAnalytics.map((row, idx) => (
                <tr key={`${row.provider}-${row.model}-${row.voice_id}`} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'}>
                  <td className="px-3 py-3 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <ProviderLogo provider={row.provider} size="sm" />
                      <span className="font-medium text-gray-800">{getProviderInfo(row.provider).label}</span>
                    </div>
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-gray-600 font-mono text-xs">{row.model}</td>
                  <td className="px-3 py-3 whitespace-nowrap text-gray-700">{row.voice_name}</td>
                  <td className="px-3 py-3 whitespace-nowrap text-center">
                    <span className="px-2 py-0.5 bg-gray-100 text-gray-700 rounded-full text-xs font-medium">{row.sample_count}</span>
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-center">
                    <AnalyticsMetricCell value={row.avg_mos} max={maxMos} higherIsBetter />
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-center">
                    <AnalyticsMetricCell value={row.avg_valence} higherIsBetter />
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-center">
                    <AnalyticsMetricCell value={row.avg_arousal} higherIsBetter />
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-center">
                    <AnalyticsMetricCell value={row.avg_prosody} higherIsBetter />
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-center">
                    <AnalyticsMetricCell value={row.avg_ttfb_ms} max={maxTtfb} unit="ms" higherIsBetter={false} />
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-center">
                    <AnalyticsMetricCell value={row.avg_latency_ms} max={maxLatency} unit="ms" higherIsBetter={false} />
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-center">
                    <AnalyticsMetricCell value={row.avg_wer} unit="%" higherIsBetter={false} />
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-center">
                    <AnalyticsMetricCell value={row.avg_cer} unit="%" higherIsBetter={false} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
