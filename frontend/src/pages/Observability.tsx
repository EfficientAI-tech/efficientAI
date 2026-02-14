import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { useState, useMemo } from 'react'
import { motion } from 'framer-motion'
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { TrendingUp, Activity, Clock, CheckCircle, Loader, BarChart3, Layers, Target, Zap } from 'lucide-react'

interface EvaluatorResult {
  id: string
  result_id: string
  name: string
  timestamp: string
  duration_seconds: number | null
  status: 'queued' | 'transcribing' | 'evaluating' | 'completed' | 'failed'
  metric_scores: Record<string, { value: any; type: string; metric_name: string }> | null
  error_message: string | null
}

interface Metric {
  id: string
  name: string
  metric_type: 'number' | 'boolean' | 'rating'
  enabled: boolean
}

type TimeFilter = 1 | 4 | 7 | 30
type ChartType = 'bar' | 'line' | 'area'

// Modern color palette
const CHART_COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#f97316', '#eab308', '#22c55e']
const STATUS_COLORS: Record<string, string> = {
  completed: '#10b981',
  failed: '#f43f5e',
  queued: '#94a3b8',
  transcribing: '#3b82f6',
  evaluating: '#8b5cf6',
}

// Custom tooltip for charts
const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-white/95 backdrop-blur-sm border border-gray-200 rounded-xl shadow-lg p-3 min-w-[160px]">
      <p className="text-xs font-medium text-gray-500 mb-2">{label}</p>
      {payload.map((entry: any, index: number) => (
        <div key={index} className="flex items-center justify-between gap-4 py-0.5">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
            <span className="text-xs text-gray-700">{entry.name}</span>
          </div>
          <span className="text-xs font-semibold text-gray-900 tabular-nums">
            {typeof entry.value === 'number' ? entry.value.toFixed(2) : entry.value}
          </span>
        </div>
      ))}
    </div>
  )
}

export default function Observability() {
  const [timeFilter, setTimeFilter] = useState<TimeFilter>(7)
  const [trendsChartType, setTrendsChartType] = useState<ChartType>('area')
  const [averagesChartType, setAveragesChartType] = useState<ChartType>('bar')

  const { data: results = [], isLoading: loadingResults } = useQuery({
    queryKey: ['evaluator-results'],
    queryFn: () => apiClient.listEvaluatorResults(),
  })

  const { data: metrics = [] } = useQuery({
    queryKey: ['metrics'],
    queryFn: () => apiClient.listMetrics(),
  })

  const filteredResults = useMemo(() => {
    const now = new Date()
    const cutoffDate = new Date(now.getTime() - timeFilter * 24 * 60 * 60 * 1000)
    return (results as EvaluatorResult[]).filter((result) => {
      const resultDate = new Date(result.timestamp)
      return resultDate >= cutoffDate
    })
  }, [results, timeFilter])

  const completedResults = useMemo(() => {
    return filteredResults.filter((r) => r.status === 'completed' && r.metric_scores)
  }, [filteredResults])

  const aggregateMetrics = useMemo(() => {
    const enabledMetrics = (metrics as Metric[]).filter((m) => m.enabled)
    const aggregates: Record<string, {
      name: string
      type: string
      values: number[]
      average: number
      min: number
      max: number
      count: number
    }> = {}

    enabledMetrics.forEach((metric) => {
      const values: number[] = []
      completedResults.forEach((result) => {
        const score = result.metric_scores?.[metric.id]
        if (score) {
          let numValue: number | null = null
          if (metric.metric_type === 'rating' || metric.metric_type === 'number') {
            numValue = typeof score.value === 'number' ? score.value : parseFloat(score.value)
          } else if (metric.metric_type === 'boolean') {
            numValue = score.value === true ? 1 : 0
          }
          if (numValue !== null && !isNaN(numValue)) {
            values.push(numValue)
          }
        }
      })
      if (values.length > 0) {
        aggregates[metric.id] = {
          name: metric.name,
          type: metric.metric_type,
          values,
          average: values.reduce((a, b) => a + b, 0) / values.length,
          min: Math.min(...values),
          max: Math.max(...values),
          count: values.length,
        }
      }
    })
    return aggregates
  }, [completedResults, metrics])

  const timeSeriesData = useMemo(() => {
    const enabledMetrics = (metrics as Metric[]).filter((m) => m.enabled && (m.metric_type === 'rating' || m.metric_type === 'number'))
    const dayGroups: Record<string, Record<string, number[]>> = {}
    
    completedResults.forEach((result) => {
      const date = new Date(result.timestamp)
      const dayKey = date.toISOString().split('T')[0]
      if (!dayGroups[dayKey]) {
        dayGroups[dayKey] = {}
        enabledMetrics.forEach((m) => { dayGroups[dayKey][m.id] = [] })
      }
      enabledMetrics.forEach((metric) => {
        const score = result.metric_scores?.[metric.id]
        if (score) {
          const numValue = typeof score.value === 'number' ? score.value : parseFloat(score.value)
          if (!isNaN(numValue)) {
            dayGroups[dayKey][metric.id].push(numValue)
          }
        }
      })
    })
    
    const sortedDays = Object.keys(dayGroups).sort()
    return sortedDays.map((day) => {
      const dayData: Record<string, any> = { date: day }
      enabledMetrics.forEach((metric) => {
        const values = dayGroups[day][metric.id]
        if (values.length > 0) {
          dayData[metric.name] = values.reduce((a, b) => a + b, 0) / values.length
        }
      })
      return dayData
    })
  }, [completedResults, metrics])

  const statusDistribution = useMemo(() => {
    const statusCounts: Record<string, number> = {}
    filteredResults.forEach((result) => {
      statusCounts[result.status] = (statusCounts[result.status] || 0) + 1
    })
    return Object.entries(statusCounts).map(([status, count]) => ({
      name: status.charAt(0).toUpperCase() + status.slice(1),
      value: count,
    }))
  }, [filteredResults])

  const problemResolutionMetricId = useMemo(() => {
    const metric = (metrics as Metric[]).find(
      (m) => m.name.toLowerCase().includes('problem resolution')
    )
    return metric?.id || null
  }, [metrics])

  const problemResolutionDistribution = useMemo(() => {
    if (!problemResolutionMetricId) return []
    let resolvedCount = 0
    let notResolvedCount = 0
    completedResults.forEach((result) => {
      const problemResolutionScore = result.metric_scores?.[problemResolutionMetricId]
      if (problemResolutionScore !== undefined) {
        if (problemResolutionScore.value === true) resolvedCount++
        else notResolvedCount++
      }
    })
    const distribution = []
    if (resolvedCount > 0) distribution.push({ name: 'Resolved', value: resolvedCount })
    if (notResolvedCount > 0) distribution.push({ name: 'Not Resolved', value: notResolvedCount })
    return distribution
  }, [completedResults, problemResolutionMetricId])

  const metricAverages = useMemo(() => {
    return Object.entries(aggregateMetrics)
      .map(([, data]) => ({
        name: data.name.length > 20 ? data.name.substring(0, 20) + '...' : data.name,
        fullName: data.name,
        average: data.average,
        min: data.min,
        max: data.max,
      }))
      .sort((a, b) => b.average - a.average)
  }, [aggregateMetrics])

  const overallStats = useMemo(() => {
    const totalResults = filteredResults.length
    const completedCount = filteredResults.filter((r) => r.status === 'completed').length
    const failedCount = filteredResults.filter((r) => r.status === 'failed').length
    const avgDuration = completedResults.length > 0
      ? completedResults.reduce((sum, r) => sum + (r.duration_seconds || 0), 0) / completedResults.length
      : 0
    // Calculate overall score (prefer rating metrics since they're 0-1 scale)
    const ratingMetrics = Object.values(aggregateMetrics).filter(m => m.type === 'rating')
    const overallScore = ratingMetrics.length > 0
      ? ratingMetrics.reduce((sum, m) => sum + m.average, 0) / ratingMetrics.length
      : (Object.values(aggregateMetrics).length > 0
        ? Object.values(aggregateMetrics).reduce((sum, m) => sum + m.average, 0) / Object.values(aggregateMetrics).length
        : 0)
    const overallScoreIsRating = ratingMetrics.length > 0
    let successRate = 0
    if (problemResolutionMetricId) {
      const resultsWithProblemResolution = completedResults.filter(
        (r) => r.metric_scores && r.metric_scores[problemResolutionMetricId] !== undefined
      )
      if (resultsWithProblemResolution.length > 0) {
        const resolvedCount = resultsWithProblemResolution.filter(
          (r) => r.metric_scores?.[problemResolutionMetricId]?.value === true
        ).length
        successRate = (resolvedCount / resultsWithProblemResolution.length) * 100
      }
    } else {
      successRate = totalResults > 0 ? (completedCount / totalResults) * 100 : 0
    }
    return { totalResults, completedCount, failedCount, successRate, avgDuration, overallScore, overallScoreIsRating }
  }, [filteredResults, completedResults, aggregateMetrics, problemResolutionMetricId])

  const ChartTypeSelector = ({ 
    value, 
    onChange 
  }: { 
    value: ChartType
    onChange: (type: ChartType) => void 
  }) => {
    const chartTypes: { type: ChartType; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
      { type: 'bar', label: 'Bar', icon: BarChart3 },
      { type: 'line', label: 'Line', icon: TrendingUp },
      { type: 'area', label: 'Area', icon: Layers },
    ]
    return (
      <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
        {chartTypes.map(({ type, label, icon: Icon }) => (
          <button
            key={type}
            onClick={() => onChange(type)}
            className={`flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              value === type
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
            <span>{label}</span>
          </button>
        ))}
      </div>
    )
  }

  // Metric score color helper
  const getScoreColor = (value: number, type: string) => {
    if (type === 'rating') {
      const pct = value * 100
      if (pct >= 80) return { text: 'text-emerald-700', bg: 'bg-emerald-50', bar: 'bg-emerald-500', border: 'border-emerald-200' }
      if (pct >= 60) return { text: 'text-amber-700', bg: 'bg-amber-50', bar: 'bg-amber-500', border: 'border-amber-200' }
      return { text: 'text-rose-700', bg: 'bg-rose-50', bar: 'bg-rose-500', border: 'border-rose-200' }
    }
    if (type === 'boolean') {
      const pct = value * 100
      if (pct >= 70) return { text: 'text-emerald-700', bg: 'bg-emerald-50', bar: 'bg-emerald-500', border: 'border-emerald-200' }
      if (pct >= 50) return { text: 'text-amber-700', bg: 'bg-amber-50', bar: 'bg-amber-500', border: 'border-amber-200' }
      return { text: 'text-rose-700', bg: 'bg-rose-50', bar: 'bg-rose-500', border: 'border-rose-200' }
    }
    return { text: 'text-gray-700', bg: 'bg-gray-50', bar: 'bg-gray-500', border: 'border-gray-200' }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Observability</h1>
          <p className="mt-1 text-sm text-gray-500">
            Monitor and analyze evaluation results over time
          </p>
        </div>
      </div>

      {/* Time Filter */}
      <div className="flex items-center gap-2">
        {([1, 4, 7, 30] as TimeFilter[]).map((days) => (
          <button
            key={days}
            onClick={() => setTimeFilter(days)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              timeFilter === days
                ? 'bg-gray-900 text-white shadow-sm'
                : 'bg-white text-gray-600 border border-gray-200 hover:bg-gray-50 hover:border-gray-300'
            }`}
          >
            {days === 1 ? '24h' : `${days}d`}
          </button>
        ))}
      </div>

      {loadingResults ? (
        <div className="flex items-center justify-center py-24">
          <Loader className="w-6 h-6 animate-spin text-gray-400" />
          <span className="ml-3 text-sm text-gray-500">Loading data...</span>
        </div>
      ) : filteredResults.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-16 text-center">
          <div className="w-16 h-16 rounded-2xl bg-gray-50 flex items-center justify-center mx-auto mb-4">
            <Activity className="w-8 h-8 text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-900">No data available</p>
          <p className="text-sm text-gray-500 mt-1">No results found for the selected time period.</p>
        </div>
      ) : (
        <>
          {/* Overall Statistics */}
          <motion.div
            className="grid grid-cols-2 md:grid-cols-4 gap-4"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 hover:shadow-md transition-shadow">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-indigo-50 flex items-center justify-center flex-shrink-0">
                  <Activity className="w-5 h-5 text-indigo-600" />
                </div>
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Total Runs</p>
                  <p className="text-2xl font-bold text-gray-900 mt-0.5 tabular-nums">{overallStats.totalResults}</p>
                </div>
              </div>
            </div>

            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 hover:shadow-md transition-shadow">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-emerald-50 flex items-center justify-center flex-shrink-0">
                  <Target className="w-5 h-5 text-emerald-600" />
                </div>
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Success Rate</p>
                  <p className="text-2xl font-bold text-gray-900 mt-0.5 tabular-nums">
                    {overallStats.successRate.toFixed(0)}%
                  </p>
                </div>
              </div>
            </div>

            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 hover:shadow-md transition-shadow">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-purple-50 flex items-center justify-center flex-shrink-0">
                  <Zap className="w-5 h-5 text-purple-600" />
                </div>
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Avg Score</p>
                  <p className="text-2xl font-bold text-gray-900 mt-0.5 tabular-nums">
                    {overallStats.overallScoreIsRating
                      ? `${(overallStats.overallScore * 100).toFixed(0)}%`
                      : overallStats.overallScore.toFixed(1)}
                  </p>
                </div>
              </div>
            </div>

            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 hover:shadow-md transition-shadow">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-amber-50 flex items-center justify-center flex-shrink-0">
                  <Clock className="w-5 h-5 text-amber-600" />
                </div>
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Avg Duration</p>
                  <p className="text-2xl font-bold text-gray-900 mt-0.5 tabular-nums">
                    {Math.round(overallStats.avgDuration)}s
                  </p>
                </div>
              </div>
            </div>
          </motion.div>

          {/* Charts Row - Status & Resolution Donuts */}
          <motion.div
            className="grid grid-cols-1 md:grid-cols-2 gap-6"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.1 }}
          >
            {/* Status Distribution - Donut Chart */}
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
              <h2 className="text-sm font-semibold text-gray-900 mb-4">Status Distribution</h2>
              <div className="flex items-center gap-6">
                <div className="flex-1">
                  <ResponsiveContainer width="100%" height={220}>
                    <PieChart>
                      <Pie
                        data={statusDistribution}
                        cx="50%"
                        cy="50%"
                        innerRadius={55}
                        outerRadius={85}
                        paddingAngle={3}
                        dataKey="value"
                        strokeWidth={0}
                      >
                        {statusDistribution.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={STATUS_COLORS[entry.name.toLowerCase()] || '#94a3b8'} />
                        ))}
                      </Pie>
                      <Tooltip content={<CustomTooltip />} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="space-y-2.5 min-w-[120px]">
                  {statusDistribution.map((entry, index) => (
                    <div key={index} className="flex items-center gap-2">
                      <span
                        className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                        style={{ backgroundColor: STATUS_COLORS[entry.name.toLowerCase()] || '#94a3b8' }}
                      />
                      <span className="text-xs text-gray-600 flex-1">{entry.name}</span>
                      <span className="text-xs font-semibold text-gray-900 tabular-nums">{entry.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Problem Resolution - Donut Chart */}
            {problemResolutionDistribution.length > 0 ? (
              <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
                <h2 className="text-sm font-semibold text-gray-900 mb-4">Problem Resolution</h2>
                <div className="flex items-center gap-6">
                  <div className="flex-1">
                    <ResponsiveContainer width="100%" height={220}>
                      <PieChart>
                        <Pie
                          data={problemResolutionDistribution}
                          cx="50%"
                          cy="50%"
                          innerRadius={55}
                          outerRadius={85}
                          paddingAngle={3}
                          dataKey="value"
                          strokeWidth={0}
                        >
                          {problemResolutionDistribution.map((entry, index) => (
                            <Cell 
                              key={`pr-cell-${index}`} 
                              fill={entry.name === 'Resolved' ? '#10b981' : '#f43f5e'} 
                            />
                          ))}
                        </Pie>
                        <Tooltip content={<CustomTooltip />} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="space-y-2.5 min-w-[120px]">
                    {problemResolutionDistribution.map((entry, index) => (
                      <div key={index} className="flex items-center gap-2">
                        <span
                          className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                          style={{ backgroundColor: entry.name === 'Resolved' ? '#10b981' : '#f43f5e' }}
                        />
                        <span className="text-xs text-gray-600 flex-1">{entry.name}</span>
                        <span className="text-xs font-semibold text-gray-900 tabular-nums">{entry.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 flex items-center justify-center">
                <div className="text-center">
                  <div className="w-12 h-12 rounded-xl bg-gray-50 flex items-center justify-center mx-auto mb-3">
                    <CheckCircle className="w-6 h-6 text-gray-300" />
                  </div>
                  <p className="text-xs text-gray-500">No problem resolution data yet</p>
                </div>
              </div>
            )}
          </motion.div>

          {/* Metric Trends Over Time */}
          {timeSeriesData.length > 0 && (
            <motion.div
              className="bg-white rounded-xl border border-gray-100 shadow-sm p-6"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.15 }}
            >
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-sm font-semibold text-gray-900">Metric Trends</h2>
                  <p className="text-xs text-gray-500 mt-0.5">Average metric scores over time</p>
                </div>
                <ChartTypeSelector value={trendsChartType} onChange={setTrendsChartType} />
              </div>
              <ResponsiveContainer width="100%" height={350}>
                {trendsChartType === 'bar' ? (
                  <BarChart data={timeSeriesData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis 
                      dataKey="date" 
                      tickFormatter={(value: string) => {
                        const date = new Date(value)
                        return `${date.getMonth() + 1}/${date.getDate()}`
                      }}
                      tick={{ fontSize: 11, fill: '#94a3b8' }}
                      axisLine={{ stroke: '#e2e8f0' }}
                      tickLine={false}
                    />
                    <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                    <Tooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: '12px' }} />
                    {Object.keys(timeSeriesData[0] || {})
                      .filter((key) => key !== 'date')
                      .slice(0, 5)
                      .map((metricName, index) => (
                        <Bar key={metricName} dataKey={metricName} fill={CHART_COLORS[index % CHART_COLORS.length]} radius={[4, 4, 0, 0]} />
                      ))}
                  </BarChart>
                ) : trendsChartType === 'line' ? (
                  <LineChart data={timeSeriesData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis 
                      dataKey="date" 
                      tickFormatter={(value: string) => {
                        const date = new Date(value)
                        return `${date.getMonth() + 1}/${date.getDate()}`
                      }}
                      tick={{ fontSize: 11, fill: '#94a3b8' }}
                      axisLine={{ stroke: '#e2e8f0' }}
                      tickLine={false}
                    />
                    <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                    <Tooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: '12px' }} />
                    {Object.keys(timeSeriesData[0] || {})
                      .filter((key) => key !== 'date')
                      .slice(0, 5)
                      .map((metricName, index) => (
                        <Line
                          key={metricName}
                          type="monotone"
                          dataKey={metricName}
                          stroke={CHART_COLORS[index % CHART_COLORS.length]}
                          strokeWidth={2}
                          dot={{ r: 3, strokeWidth: 0, fill: CHART_COLORS[index % CHART_COLORS.length] }}
                          activeDot={{ r: 5, strokeWidth: 2, stroke: '#fff' }}
                        />
                      ))}
                  </LineChart>
                ) : (
                  <AreaChart data={timeSeriesData}>
                    <defs>
                      {Object.keys(timeSeriesData[0] || {})
                        .filter((key) => key !== 'date')
                        .slice(0, 5)
                        .map((metricName, index) => (
                          <linearGradient key={`gradient-${metricName}`} id={`gradient-${index}`} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={CHART_COLORS[index % CHART_COLORS.length]} stopOpacity={0.3} />
                            <stop offset="100%" stopColor={CHART_COLORS[index % CHART_COLORS.length]} stopOpacity={0.02} />
                          </linearGradient>
                        ))}
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis 
                      dataKey="date" 
                      tickFormatter={(value: string) => {
                        const date = new Date(value)
                        return `${date.getMonth() + 1}/${date.getDate()}`
                      }}
                      tick={{ fontSize: 11, fill: '#94a3b8' }}
                      axisLine={{ stroke: '#e2e8f0' }}
                      tickLine={false}
                    />
                    <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                    <Tooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: '12px' }} />
                    {Object.keys(timeSeriesData[0] || {})
                      .filter((key) => key !== 'date')
                      .slice(0, 5)
                      .map((metricName, index) => (
                        <Area
                          key={metricName}
                          type="monotone"
                          dataKey={metricName}
                          stroke={CHART_COLORS[index % CHART_COLORS.length]}
                          fill={`url(#gradient-${index})`}
                          strokeWidth={2}
                        />
                      ))}
                  </AreaChart>
                )}
              </ResponsiveContainer>
            </motion.div>
          )}

          {/* Metric Averages Chart */}
          {metricAverages.length > 0 && (
            <motion.div
              className="bg-white rounded-xl border border-gray-100 shadow-sm p-6"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.2 }}
            >
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-sm font-semibold text-gray-900">Metric Averages</h2>
                  <p className="text-xs text-gray-500 mt-0.5">Aggregate scores across all evaluations</p>
                </div>
                <ChartTypeSelector value={averagesChartType} onChange={setAveragesChartType} />
              </div>
              <ResponsiveContainer width="100%" height={350}>
                {averagesChartType === 'bar' ? (
                  <BarChart data={metricAverages}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis 
                      dataKey="name" 
                      angle={-45}
                      textAnchor="end"
                      height={100}
                      tick={{ fontSize: 11, fill: '#94a3b8' }}
                      axisLine={{ stroke: '#e2e8f0' }}
                      tickLine={false}
                    />
                    <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                    <Tooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: '12px' }} />
                    <Bar dataKey="average" fill="#6366f1" name="Average" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="min" fill="#c7d2fe" name="Min" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="max" fill="#a78bfa" name="Max" radius={[4, 4, 0, 0]} />
                  </BarChart>
                ) : averagesChartType === 'line' ? (
                  <LineChart data={metricAverages}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis 
                      dataKey="name" 
                      angle={-45}
                      textAnchor="end"
                      height={100}
                      tick={{ fontSize: 11, fill: '#94a3b8' }}
                      axisLine={{ stroke: '#e2e8f0' }}
                      tickLine={false}
                    />
                    <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                    <Tooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: '12px' }} />
                    <Line type="monotone" dataKey="average" stroke="#6366f1" strokeWidth={2} dot={{ r: 4, fill: '#6366f1', strokeWidth: 0 }} name="Average" />
                    <Line type="monotone" dataKey="min" stroke="#c7d2fe" strokeWidth={2} dot={{ r: 4, fill: '#c7d2fe', strokeWidth: 0 }} name="Min" />
                    <Line type="monotone" dataKey="max" stroke="#a78bfa" strokeWidth={2} dot={{ r: 4, fill: '#a78bfa', strokeWidth: 0 }} name="Max" />
                  </LineChart>
                ) : (
                  <AreaChart data={metricAverages}>
                    <defs>
                      <linearGradient id="avgGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#6366f1" stopOpacity={0.3} />
                        <stop offset="100%" stopColor="#6366f1" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis 
                      dataKey="name" 
                      angle={-45}
                      textAnchor="end"
                      height={100}
                      tick={{ fontSize: 11, fill: '#94a3b8' }}
                      axisLine={{ stroke: '#e2e8f0' }}
                      tickLine={false}
                    />
                    <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                    <Tooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: '12px' }} />
                    <Area type="monotone" dataKey="average" stroke="#6366f1" fill="url(#avgGrad)" strokeWidth={2} name="Average" />
                    <Area type="monotone" dataKey="min" stroke="#c7d2fe" fill="#c7d2fe" fillOpacity={0.1} strokeWidth={2} name="Min" />
                    <Area type="monotone" dataKey="max" stroke="#a78bfa" fill="#a78bfa" fillOpacity={0.1} strokeWidth={2} name="Max" />
                  </AreaChart>
                )}
              </ResponsiveContainer>
            </motion.div>
          )}

          {/* Detailed Metric Breakdown - Card Grid */}
          {Object.keys(aggregateMetrics).length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.25 }}
            >
              <div className="mb-4">
                <h2 className="text-sm font-semibold text-gray-900">Metric Breakdown</h2>
                <p className="text-xs text-gray-500 mt-0.5">Individual metric performance</p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                {Object.entries(aggregateMetrics)
                  .sort(([, a], [, b]) => b.average - a.average)
                  .map(([id, data], index) => {
                    const scoreColor = getScoreColor(data.average, data.type)
                    const isRating = data.type === 'rating'
                    const displayValue = isRating ? `${(data.average * 100).toFixed(0)}%` : data.average.toFixed(2)
                    const barWidth = isRating ? data.average * 100 : Math.min(data.average * 100, 100)
                    
                    return (
                      <motion.div
                        key={id}
                        className={`bg-white rounded-xl border shadow-sm p-4 hover:shadow-md transition-all ${scoreColor.border}`}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.2, delay: 0.03 * index }}
                      >
                        <div className="flex items-start justify-between mb-3">
                          <div>
                            <h3 className="text-sm font-medium text-gray-900">{data.name}</h3>
                            <span className="text-[10px] font-medium text-gray-400 uppercase tracking-wider">{data.type}</span>
                          </div>
                          <span className={`text-lg font-bold tabular-nums ${scoreColor.text}`}>
                            {displayValue}
                          </span>
                        </div>
                        
                        {/* Progress bar */}
                        <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden mb-3">
                          <motion.div
                            className={`h-full rounded-full ${scoreColor.bar}`}
                            initial={{ width: 0 }}
                            animate={{ width: `${barWidth}%` }}
                            transition={{ duration: 0.8, ease: 'easeOut', delay: 0.1 * index }}
                          />
                        </div>
                        
                        {/* Min / Max / Count */}
                        <div className="flex items-center gap-3 text-[11px] text-gray-500">
                          <span>Min: <span className="font-medium text-gray-700 tabular-nums">{isRating ? `${(data.min * 100).toFixed(0)}%` : data.min.toFixed(2)}</span></span>
                          <span>Max: <span className="font-medium text-gray-700 tabular-nums">{isRating ? `${(data.max * 100).toFixed(0)}%` : data.max.toFixed(2)}</span></span>
                          <span className="ml-auto">n={data.count}</span>
                        </div>
                      </motion.div>
                    )
                  })}
              </div>
            </motion.div>
          )}
        </>
      )}
    </div>
  )
}
