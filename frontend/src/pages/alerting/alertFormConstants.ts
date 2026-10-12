export const DATA_SOURCES = [
  { value: 'evaluations', label: 'Synthetic evaluations' },
  { value: 'production_calls', label: 'Production calls (webhooks)' },
  { value: 'production_traces', label: 'Production traces (ClickHouse)' },
  { value: 'cron_jobs', label: 'Scheduled cron jobs' },
]

const METRICS_BY_SOURCE: Record<string, string[]> = {
  evaluations: ['number_of_calls', 'call_duration', 'error_rate', 'success_rate', 'latency', 'custom'],
  production_calls: ['number_of_calls', 'call_duration', 'error_rate', 'success_rate'],
  production_traces: ['number_of_calls', 'call_duration', 'error_rate', 'success_rate', 'latency'],
  cron_jobs: ['failure_count'],
}

export const ALL_METRIC_TYPES = [
  { value: 'number_of_calls', label: 'Number of Calls' },
  { value: 'call_duration', label: 'Call Duration' },
  { value: 'error_rate', label: 'Error Rate' },
  { value: 'success_rate', label: 'Success Rate' },
  { value: 'latency', label: 'Latency (eval: call duration proxy)' },
  { value: 'custom', label: 'Custom' },
  { value: 'failure_count', label: 'Failed cron jobs' },
]

export function metricTypesForDataSource(dataSource: string) {
  const allowed = METRICS_BY_SOURCE[dataSource] || METRICS_BY_SOURCE.evaluations
  return ALL_METRIC_TYPES.filter(m => allowed.includes(m.value))
}
