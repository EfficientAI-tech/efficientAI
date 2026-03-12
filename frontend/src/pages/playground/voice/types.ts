export interface TTSVoice {
  id: string
  name: string
  gender: string
  accent: string
  is_custom?: boolean
  custom_voice_id?: string
  description?: string
}

export interface TTSProvider {
  provider: string
  models: string[]
  voices: TTSVoice[]
  model_voices?: Record<string, TTSVoice[]>
  supported_sample_rates?: number[]
}

export interface TTSSample {
  id: string
  provider: string
  model: string
  voice_id: string
  voice_name: string
  side?: string | null
  sample_index: number
  run_index: number
  text: string
  audio_url: string | null
  audio_s3_key: string | null
  duration_seconds: number | null
  latency_ms: number | null
  ttfb_ms: number | null
  evaluation_metrics: Record<string, number | string | null> | null
  status: string
  error_message: string | null
}

export interface TTSComparison {
  id: string
  simulation_id: string | null
  name: string
  status: string
  provider_a: string
  model_a: string
  voices_a: Array<{ id: string; name: string; sample_rate_hz?: number }>
  provider_b?: string | null
  model_b?: string | null
  voices_b?: Array<{ id: string; name: string; sample_rate_hz?: number }>
  sample_texts: string[]
  num_runs: number
  blind_test_results: Array<{ sample_index: number; preferred: string }> | null
  evaluation_summary: Record<string, any> | null
  error_message: string | null
  samples: TTSSample[]
  created_at: string
  updated_at: string
}

export interface TTSComparisonSummary {
  id: string
  simulation_id: string | null
  name: string
  status: string
  provider_a: string
  model_a: string
  provider_b?: string | null
  model_b?: string | null
  sample_count: number
  num_runs: number
  created_at: string
}

export interface TTSAnalyticsRow {
  provider: string
  model: string
  voice_id: string
  voice_name: string
  sample_count: number
  avg_mos: number | null
  avg_valence: number | null
  avg_arousal: number | null
  avg_prosody: number | null
  avg_latency_ms: number | null
  avg_ttfb_ms: number | null
  avg_wer: number | null
  avg_cer: number | null
}

export interface CustomTTSVoice {
  id: string
  provider: string
  voice_id: string
  name: string
  gender: string
  accent: string
  description?: string | null
  is_custom: boolean
  created_at?: string | null
  updated_at?: string | null
}

export interface TTSReportJob {
  id: string
  comparison_id: string
  status: 'pending' | 'processing' | 'completed' | 'failed' | string
  format: string
  filename?: string | null
  error_message?: string | null
  task_id?: string | null
  download_url?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export type AnalyticsSortKey =
  | 'provider'
  | 'model'
  | 'voice_name'
  | 'sample_count'
  | 'avg_mos'
  | 'avg_valence'
  | 'avg_arousal'
  | 'avg_prosody'
  | 'avg_latency_ms'
  | 'avg_ttfb_ms'
  | 'avg_wer'
  | 'avg_cer'

export type BenchmarkMetricKey =
  | 'avg_mos'
  | 'avg_valence'
  | 'avg_arousal'
  | 'avg_prosody'
  | 'avg_latency_ms'
  | 'avg_ttfb_ms'
  | 'avg_wer'
  | 'avg_cer'

export const BENCHMARK_METRIC_OPTIONS: Array<{
  key: BenchmarkMetricKey
  title: string
  subtitle: string
  higherIsBetter: boolean
  maxValue?: number
  unit?: string
}> = [
  {
    key: 'avg_mos',
    title: 'INTELLIGENCE',
    subtitle: 'Average MOS Score; Higher is better',
    higherIsBetter: true,
    maxValue: 5,
  },
  {
    key: 'avg_valence',
    title: 'VALENCE',
    subtitle: 'Average Emotional Valence; Higher is better',
    higherIsBetter: true,
    maxValue: 1,
  },
  {
    key: 'avg_arousal',
    title: 'AROUSAL',
    subtitle: 'Average Emotional Arousal; Higher is better',
    higherIsBetter: true,
    maxValue: 1,
  },
  {
    key: 'avg_prosody',
    title: 'PROSODY',
    subtitle: 'Average Prosody Score; Higher is better',
    higherIsBetter: true,
    maxValue: 5,
  },
  {
    key: 'avg_ttfb_ms',
    title: 'TTFB',
    subtitle: 'Time-To-First-Byte (ms); Lower is better',
    higherIsBetter: false,
    unit: 'ms',
  },
  {
    key: 'avg_latency_ms',
    title: 'TOTAL LATENCY',
    subtitle: 'Total Synthesis Latency (ms); Lower is better',
    higherIsBetter: false,
    unit: 'ms',
  },
  {
    key: 'avg_wer',
    title: 'WER',
    subtitle: 'Word Error Rate (ASR vs Ground Truth); Lower is better',
    higherIsBetter: false,
    maxValue: 1,
  },
  {
    key: 'avg_cer',
    title: 'CER',
    subtitle: 'Character Error Rate (ASR vs Ground Truth); Lower is better',
    higherIsBetter: false,
    maxValue: 1,
  },
]

export const DEFAULT_SAMPLE_TEXTS = [
  'Hello! Thank you for calling customer support. How may I assist you today?',
  'Your order number is 1-2-3-4-5-6-7-8-9. It will be delivered on January 15th, 2025.',
  'I understand your concern. Let me look into this for you right away.',
  'The total amount due is $1,234.56. Would you like to proceed with the payment?',
  'Is there anything else I can help you with today? We appreciate your business!',
]
