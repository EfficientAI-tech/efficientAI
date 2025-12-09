import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { useState, useMemo } from 'react'
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
import { TrendingUp, Activity, Clock, CheckCircle, Loader, BarChart3, Layers } from 'lucide-react'

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

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4']

export default function Observability() {
  const [timeFilter, setTimeFilter] = useState<TimeFilter>(7)
  const [trendsChartType, setTrendsChartType] = useState<ChartType>('line')
  const [averagesChartType, setAveragesChartType] = useState<ChartType>('bar')

  const { data: results = [], isLoading: loadingResults } = useQuery({
    queryKey: ['evaluator-results'],
    queryFn: () => apiClient.listEvaluatorResults(),
  })

  const { data: metrics = [] } = useQuery({
    queryKey: ['metrics'],
    queryFn: () => apiClient.listMetrics(),
  })

  // Filter results by time period
  const filteredResults = useMemo(() => {
    const now = new Date()
    const cutoffDate = new Date(now.getTime() - timeFilter * 24 * 60 * 60 * 1000)
    
    return (results as EvaluatorResult[]).filter((result) => {
      const resultDate = new Date(result.timestamp)
      return resultDate >= cutoffDate
    })
  }, [results, timeFilter])

  // Only consider completed results for metrics
  const completedResults = useMemo(() => {
    return filteredResults.filter((r) => r.status === 'completed' && r.metric_scores)
  }, [filteredResults])

  // Calculate aggregate metrics
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

  // Prepare time series data for trends
  const timeSeriesData = useMemo(() => {
    const enabledMetrics = (metrics as Metric[]).filter((m) => m.enabled && (m.metric_type === 'rating' || m.metric_type === 'number'))
    
    // Group by day
    const dayGroups: Record<string, Record<string, number[]>> = {}
    
    completedResults.forEach((result) => {
      const date = new Date(result.timestamp)
      const dayKey = date.toISOString().split('T')[0]
      
      if (!dayGroups[dayKey]) {
        dayGroups[dayKey] = {}
        enabledMetrics.forEach((m) => {
          dayGroups[dayKey][m.id] = []
        })
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
    
    // Calculate averages per day
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

  // Status distribution for pie chart
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

  // Metric averages for bar chart
  const metricAverages = useMemo(() => {
    return Object.entries(aggregateMetrics)
      .map(([, data]) => ({
        name: data.name.length > 20 ? data.name.substring(0, 20) + '...' : data.name,
        average: data.average,
        min: data.min,
        max: data.max,
      }))
      .sort((a, b) => b.average - a.average)
  }, [aggregateMetrics])

  // Find Problem Resolution metric ID
  const problemResolutionMetricId = useMemo(() => {
    const metric = (metrics as Metric[]).find(
      (m) => m.name.toLowerCase().includes('problem resolution')
    )
    return metric?.id || null
  }, [metrics])

  // Overall statistics
  const overallStats = useMemo(() => {
    const totalResults = filteredResults.length
    const completedCount = filteredResults.filter((r) => r.status === 'completed').length
    const failedCount = filteredResults.filter((r) => r.status === 'failed').length
    const avgDuration = completedResults.length > 0
      ? completedResults.reduce((sum, r) => sum + (r.duration_seconds || 0), 0) / completedResults.length
      : 0
    
    // Calculate overall score (average of all metric averages)
    const overallScore = Object.values(aggregateMetrics).length > 0
      ? Object.values(aggregateMetrics).reduce((sum, m) => sum + m.average, 0) / Object.values(aggregateMetrics).length
      : 0

    // Calculate success rate based on Problem Resolution metric
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
      // Fallback to completed status if Problem Resolution metric not found
      successRate = totalResults > 0 ? (completedCount / totalResults) * 100 : 0
    }

    return {
      totalResults,
      completedCount,
      failedCount,
      successRate,
      avgDuration,
      overallScore,
    }
  }, [filteredResults, completedResults, aggregateMetrics, problemResolutionMetricId])

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'completed':
        return '#10b981'
      case 'failed':
        return '#ef4444'
      case 'queued':
        return '#6b7280'
      case 'transcribing':
      case 'evaluating':
        return '#3b82f6'
      default:
        return '#9ca3af'
    }
  }

  // Helper function to render chart type selector
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
      <div className="flex items-center space-x-2 mb-4">
        <span className="text-sm font-medium text-gray-700">Chart Type:</span>
        {chartTypes.map(({ type, label, icon: Icon }) => (
          <button
            key={type}
            onClick={() => onChange(type)}
            className={`flex items-center space-x-1 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              value === type
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            <Icon className="w-4 h-4" />
            <span>{label}</span>
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Observability</h1>
          <p className="mt-2 text-sm text-gray-600">
            Monitor and analyze evaluation results over time
          </p>
        </div>
      </div>

      {/* Time Filter */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex items-center space-x-2">
          <span className="text-sm font-medium text-gray-700">Time Period:</span>
          {([1, 4, 7, 30] as TimeFilter[]).map((days) => (
            <button
              key={days}
              onClick={() => setTimeFilter(days)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                timeFilter === days
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              Last {days} {days === 1 ? 'Day' : 'Days'}
            </button>
          ))}
        </div>
      </div>

      {loadingResults ? (
        <div className="flex items-center justify-center p-12">
          <Loader className="w-8 h-8 animate-spin text-blue-600" />
          <span className="ml-3 text-gray-600">Loading data...</span>
        </div>
      ) : filteredResults.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <Activity className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <p className="text-gray-500">No results found for the selected time period.</p>
        </div>
      ) : (
        <>
          {/* Overall Statistics */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">Total Results</p>
                  <p className="text-2xl font-bold text-gray-900 mt-1">{overallStats.totalResults}</p>
                </div>
                <Activity className="w-8 h-8 text-blue-600" />
              </div>
            </div>

            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">Success Rate</p>
                  <p className="text-2xl font-bold text-gray-900 mt-1">
                    {overallStats.successRate.toFixed(1)}%
                  </p>
                </div>
                <CheckCircle className="w-8 h-8 text-green-600" />
              </div>
            </div>

            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">Overall Score</p>
                  <p className="text-2xl font-bold text-gray-900 mt-1">
                    {overallStats.overallScore.toFixed(1)}
                  </p>
                </div>
                <TrendingUp className="w-8 h-8 text-purple-600" />
              </div>
            </div>

            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">Avg Duration</p>
                  <p className="text-2xl font-bold text-gray-900 mt-1">
                    {Math.round(overallStats.avgDuration)}s
                  </p>
                </div>
                <Clock className="w-8 h-8 text-orange-600" />
              </div>
            </div>
          </div>

          {/* Status Distribution Pie Chart */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-xl font-bold text-gray-900 mb-4">Status Distribution</h2>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={statusDistribution}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, percent }: { name: string; percent: number }) => `${name}: ${(percent * 100).toFixed(0)}%`}
                  outerRadius={100}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {statusDistribution.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={getStatusColor(entry.name)} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* Metric Trends Over Time */}
          {timeSeriesData.length > 0 && (
            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-xl font-bold text-gray-900">Metric Trends Over Time</h2>
                <ChartTypeSelector value={trendsChartType} onChange={setTrendsChartType} />
              </div>
              <ResponsiveContainer width="100%" height={400}>
                {trendsChartType === 'bar' ? (
                  <BarChart data={timeSeriesData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis 
                      dataKey="date" 
                      tickFormatter={(value: string) => {
                        const date = new Date(value)
                        return `${date.getMonth() + 1}/${date.getDate()}`
                      }}
                    />
                    <YAxis />
                    <Tooltip 
                      labelFormatter={(value: string) => {
                        const date = new Date(value)
                        return date.toLocaleDateString()
                      }}
                    />
                    <Legend />
                    {Object.keys(timeSeriesData[0] || {})
                      .filter((key) => key !== 'date')
                      .slice(0, 5)
                      .map((metricName, index) => (
                        <Bar
                          key={metricName}
                          dataKey={metricName}
                          fill={COLORS[index % COLORS.length]}
                          name={metricName}
                        />
                      ))}
                  </BarChart>
                ) : trendsChartType === 'line' ? (
                  <LineChart data={timeSeriesData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis 
                      dataKey="date" 
                      tickFormatter={(value: string) => {
                        const date = new Date(value)
                        return `${date.getMonth() + 1}/${date.getDate()}`
                      }}
                    />
                    <YAxis />
                    <Tooltip 
                      labelFormatter={(value: string) => {
                        const date = new Date(value)
                        return date.toLocaleDateString()
                      }}
                    />
                    <Legend />
                    {Object.keys(timeSeriesData[0] || {})
                      .filter((key) => key !== 'date')
                      .slice(0, 5)
                      .map((metricName, index) => (
                        <Line
                          key={metricName}
                          type="monotone"
                          dataKey={metricName}
                          stroke={COLORS[index % COLORS.length]}
                          strokeWidth={2}
                          dot={{ r: 4 }}
                        />
                      ))}
                  </LineChart>
                ) : (
                  <AreaChart data={timeSeriesData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis 
                      dataKey="date" 
                      tickFormatter={(value: string) => {
                        const date = new Date(value)
                        return `${date.getMonth() + 1}/${date.getDate()}`
                      }}
                    />
                    <YAxis />
                    <Tooltip 
                      labelFormatter={(value: string) => {
                        const date = new Date(value)
                        return date.toLocaleDateString()
                      }}
                    />
                    <Legend />
                    {Object.keys(timeSeriesData[0] || {})
                      .filter((key) => key !== 'date')
                      .slice(0, 5)
                      .map((metricName, index) => (
                        <Area
                          key={metricName}
                          type="monotone"
                          dataKey={metricName}
                          stroke={COLORS[index % COLORS.length]}
                          fill={COLORS[index % COLORS.length]}
                          fillOpacity={0.6}
                          strokeWidth={2}
                        />
                      ))}
                  </AreaChart>
                )}
              </ResponsiveContainer>
            </div>
          )}

          {/* Metric Averages Chart */}
          {metricAverages.length > 0 && (
            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-xl font-bold text-gray-900">Metric Averages</h2>
                <ChartTypeSelector value={averagesChartType} onChange={setAveragesChartType} />
              </div>
              <ResponsiveContainer width="100%" height={400}>
                {averagesChartType === 'bar' ? (
                  <BarChart data={metricAverages}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis 
                      dataKey="name" 
                      angle={-45}
                      textAnchor="end"
                      height={100}
                    />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="average" fill="#3b82f6" name="Average" />
                    <Bar dataKey="min" fill="#ef4444" name="Min" />
                    <Bar dataKey="max" fill="#10b981" name="Max" />
                  </BarChart>
                ) : averagesChartType === 'line' ? (
                  <LineChart data={metricAverages}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis 
                      dataKey="name" 
                      angle={-45}
                      textAnchor="end"
                      height={100}
                    />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Line type="monotone" dataKey="average" stroke="#3b82f6" strokeWidth={2} dot={{ r: 4 }} name="Average" />
                    <Line type="monotone" dataKey="min" stroke="#ef4444" strokeWidth={2} dot={{ r: 4 }} name="Min" />
                    <Line type="monotone" dataKey="max" stroke="#10b981" strokeWidth={2} dot={{ r: 4 }} name="Max" />
                  </LineChart>
                ) : (
                  <AreaChart data={metricAverages}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis 
                      dataKey="name" 
                      angle={-45}
                      textAnchor="end"
                      height={100}
                    />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Area type="monotone" dataKey="average" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.6} strokeWidth={2} name="Average" />
                    <Area type="monotone" dataKey="min" stroke="#ef4444" fill="#ef4444" fillOpacity={0.6} strokeWidth={2} name="Min" />
                    <Area type="monotone" dataKey="max" stroke="#10b981" fill="#10b981" fillOpacity={0.6} strokeWidth={2} name="Max" />
                  </AreaChart>
                )}
              </ResponsiveContainer>
            </div>
          )}

          {/* Detailed Metric Breakdown */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-xl font-bold text-gray-900 mb-4">Detailed Metric Breakdown</h2>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Metric
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Type
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Average
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Min
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Max
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Count
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {Object.entries(aggregateMetrics)
                    .sort(([, a], [, b]) => b.average - a.average)
                    .map(([id, data]) => (
                      <tr key={id} className="hover:bg-gray-50">
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                          {data.name}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {data.type}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          {data.average.toFixed(2)}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          {data.min.toFixed(2)}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          {data.max.toFixed(2)}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {data.count}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

