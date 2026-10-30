import { hashString, mulberry32 } from './mockCatalog'

export const USD_TO_INR = 84

export type ModelKind = 'stt' | 'tts' | 'llm' | 's2s'
export type ModelUnit = 'per_minute' | 'per_1m_tokens'
export type Currency = 'USD' | 'INR'

export interface MockModelDef {
  id: string
  name: string
  kind: ModelKind
  unit: ModelUnit
  basePriceUsd: number
}

export const MOCK_MODELS: MockModelDef[] = [
  { id: 'deepgram-nova-2', name: 'Deepgram Nova-2', kind: 'stt', unit: 'per_minute', basePriceUsd: 0.0043 },
  { id: 'whisper-large-v3', name: 'Whisper Large v3', kind: 'stt', unit: 'per_minute', basePriceUsd: 0.006 },
  { id: 'elevenlabs-flash', name: 'ElevenLabs Flash', kind: 'tts', unit: 'per_minute', basePriceUsd: 0.15 },
  { id: 'cartesia-sonic', name: 'Cartesia Sonic', kind: 'tts', unit: 'per_minute', basePriceUsd: 0.08 },
  { id: 'gpt-4o-mini', name: 'GPT-4o mini', kind: 'llm', unit: 'per_1m_tokens', basePriceUsd: 0.15 },
  { id: 'claude-haiku', name: 'Claude 3.5 Haiku', kind: 'llm', unit: 'per_1m_tokens', basePriceUsd: 0.8 },
  { id: 'gpt-4o-realtime', name: 'GPT-4o Realtime', kind: 's2s', unit: 'per_minute', basePriceUsd: 0.06 },
  { id: 'gemini-live', name: 'Gemini Live', kind: 's2s', unit: 'per_minute', basePriceUsd: 0.035 },
]

const MODEL_BY_ID: Record<string, MockModelDef> = Object.fromEntries(
  MOCK_MODELS.map((model) => [model.id, model]),
)

export function modelById(id: string): MockModelDef | undefined {
  return MODEL_BY_ID[id]
}

export function modelsByKind(kind: ModelKind): MockModelDef[] {
  return MOCK_MODELS.filter((model) => model.kind === kind)
}

export interface CallModelUsage {
  modelId: string
  minutes: number
  tokens: number
  latencyMs: number
  costUsd: number
}

export interface CallUsage {
  mode: 'cascade' | 's2s'
  stt?: CallModelUsage
  tts?: CallModelUsage
  llm?: CallModelUsage
  s2s?: CallModelUsage
  costUsd: number
  tokens: number
  minutes: number
  latencyMs: number
}

function dayKey(date: Date): string {
  return date.toISOString().slice(0, 10)
}

export function unitPriceUsd(modelId: string, at: Date): number {
  const model = MODEL_BY_ID[modelId]
  if (!model) return 0
  const rng = mulberry32(hashString(`${modelId}|${dayKey(at)}`))
  const dayIndex = Math.floor(at.getTime() / 86400000)
  const drift = (dayIndex % 97) / 97
  const wave = Math.sin(dayIndex / 11 + model.basePriceUsd * 40) * 0.06
  const noise = (rng() - 0.5) * 0.04
  return Number((model.basePriceUsd * (1 + wave + noise + (drift - 0.5) * 0.08)).toFixed(6))
}

export function modelPriceHistory(
  modelId: string,
  from: Date,
  to: Date,
): Array<{ day: string; price: number }> {
  const rows: Array<{ day: string; price: number }> = []
  const cursor = new Date(from)
  cursor.setHours(12, 0, 0, 0)
  const end = new Date(to)
  end.setHours(12, 0, 0, 0)
  while (cursor <= end) {
    rows.push({ day: dayKey(cursor), price: unitPriceUsd(modelId, cursor) })
    cursor.setDate(cursor.getDate() + 1)
  }
  return rows
}

function costFor(modelId: string, at: Date, minutes: number, tokens: number): number {
  const model = MODEL_BY_ID[modelId]
  if (!model) return 0
  const price = unitPriceUsd(modelId, at)
  if (model.unit === 'per_minute') return minutes * price
  return (tokens / 1_000_000) * price
}

function pick(ids: string[], rng: () => number): string {
  return ids[Math.floor(rng() * ids.length)] ?? ids[0]
}

export function buildCallUsage(params: {
  agentId: string
  durationSeconds: number
  startedAt: string
  rng: () => number
}): CallUsage {
  const at = new Date(params.startedAt)
  const minutes = Math.max(0.2, params.durationSeconds / 60)
  const tokens = Math.round(params.durationSeconds * (12 + params.rng() * 18))
  const s2sChance =
    params.agentId === 'mock-agent-sales-outbound'
      ? 0.7
      : params.agentId === 'mock-agent-billing'
        ? 0.1
        : 0.2
  if (params.rng() < s2sChance) {
    const modelId =
      params.agentId === 'mock-agent-billing'
        ? pick(['gemini-live', 'gpt-4o-realtime'], params.rng)
        : pick(['gpt-4o-realtime', 'gemini-live'], params.rng)
    const latencyMs = Math.round(180 + params.rng() * 420)
    const costUsd = costFor(modelId, at, minutes, tokens)
    const s2s: CallModelUsage = { modelId, minutes, tokens, latencyMs, costUsd }
    return {
      mode: 's2s',
      s2s,
      costUsd,
      tokens,
      minutes,
      latencyMs,
    }
  }

  const sttId =
    params.agentId === 'mock-agent-billing'
      ? pick(['whisper-large-v3', 'deepgram-nova-2'], params.rng)
      : pick(['deepgram-nova-2', 'whisper-large-v3'], params.rng)
  const ttsId =
    params.agentId === 'mock-agent-sales-outbound'
      ? pick(['cartesia-sonic', 'elevenlabs-flash'], params.rng)
      : pick(['elevenlabs-flash', 'cartesia-sonic'], params.rng)
  const llmId =
    params.agentId === 'mock-agent-billing'
      ? pick(['claude-haiku', 'gpt-4o-mini'], params.rng)
      : pick(['gpt-4o-mini', 'claude-haiku'], params.rng)
  const stt: CallModelUsage = {
    modelId: sttId,
    minutes,
    tokens: 0,
    latencyMs: Math.round(90 + params.rng() * 160),
    costUsd: costFor(sttId, at, minutes, 0),
  }
  const tts: CallModelUsage = {
    modelId: ttsId,
    minutes: minutes * (0.45 + params.rng() * 0.2),
    tokens: 0,
    latencyMs: Math.round(110 + params.rng() * 240),
    costUsd: 0,
  }
  tts.costUsd = costFor(ttsId, at, tts.minutes, 0)
  const llm: CallModelUsage = {
    modelId: llmId,
    minutes: 0,
    tokens,
    latencyMs: Math.round(220 + params.rng() * 780),
    costUsd: costFor(llmId, at, 0, tokens),
  }
  return {
    mode: 'cascade',
    stt,
    tts,
    llm,
    costUsd: stt.costUsd + tts.costUsd + llm.costUsd,
    tokens,
    minutes,
    latencyMs: Math.max(stt.latencyMs, tts.latencyMs, llm.latencyMs),
  }
}

export function convertUsd(amountUsd: number, currency: Currency): number {
  return currency === 'INR' ? amountUsd * USD_TO_INR : amountUsd
}

export function formatMoney(amountUsd: number, currency: Currency): string {
  const value = convertUsd(amountUsd, currency)
  if (currency === 'INR') {
    return `₹${value.toLocaleString('en-IN', { maximumFractionDigits: value >= 100 ? 0 : 2 })}`
  }
  return `$${value.toLocaleString('en-US', { maximumFractionDigits: value >= 10 ? 2 : 3 })}`
}

export function usageModels(usage: CallUsage): CallModelUsage[] {
  return [usage.stt, usage.tts, usage.llm, usage.s2s].filter((item): item is CallModelUsage => Boolean(item))
}
