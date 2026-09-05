export type ProviderCostUnit = 'usd' | 'credits'

export interface ProviderCostSummary {
  total: number
  unit: ProviderCostUnit
  creditNote?: number
}

function toNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

export function extractProviderCostSummary(
  platform: string | null | undefined,
  callData: Record<string, unknown>,
): ProviderCostSummary | null {
  const plat = (platform || '').toLowerCase()

  if (plat === 'elevenlabs') {
    const metadata = (callData.raw_data as { metadata?: Record<string, unknown> } | undefined)?.metadata
    const charging = metadata?.charging as
      | { llm_price?: number; platform_price?: number }
      | undefined
    const fiat = toNumber(metadata?.cost_fiat)
    if (fiat != null) {
      return {
        total: fiat,
        unit: 'usd',
        creditNote: toNumber(callData.cost ?? metadata?.cost) ?? undefined,
      }
    }
    if (charging) {
      const llm = toNumber(charging.llm_price) || 0
      const platformPrice = toNumber(charging.platform_price) || 0
      if (llm > 0 || platformPrice > 0) {
        return {
          total: llm + platformPrice,
          unit: 'usd',
          creditNote: toNumber(callData.cost ?? metadata?.cost) ?? undefined,
        }
      }
    }
    return null
  }

  if (plat === 'retell') {
    const callCost = callData.call_cost as { combined_cost?: number } | undefined
    const cents = toNumber(callCost?.combined_cost)
    if (cents != null) return { total: cents / 100, unit: 'usd' }
    return null
  }

  if (plat === 'smallest') {
    const raw = (callData.raw_data || {}) as Record<string, unknown>
    const rawCost = raw.callCost
    if (rawCost && typeof rawCost === 'object') {
      const costObj = rawCost as Record<string, unknown>
      const callCharge = toNumber(costObj.callCharge) || toNumber(costObj.call) || 0
      const llmCharge = toNumber(costObj.llmCharge) || toNumber(costObj.llm) || 0
      const total =
        toNumber(costObj.total) ||
        toNumber(costObj.totalCredits) ||
        (callCharge + llmCharge > 0 ? callCharge + llmCharge : null)
      if (total != null && total > 0) return { total, unit: 'credits' }
    }
    const analysisCost = toNumber((callData.analysis as { cost?: number } | undefined)?.cost)
    if (analysisCost != null && analysisCost > 0) return { total: analysisCost, unit: 'credits' }
    const topCost = toNumber(raw.cost) || toNumber(callData.cost)
    if (topCost != null && topCost > 0) return { total: topCost, unit: 'credits' }
    return null
  }

  const breakdown = (callData.cost_breakdown || callData.costBreakdown) as { total?: number } | undefined
  const breakdownTotal = toNumber(breakdown?.total)
  if (breakdownTotal != null) return { total: breakdownTotal, unit: 'usd' }

  const direct = toNumber(callData.cost)
  if (direct != null) return { total: direct, unit: 'usd' }

  const retellFallback = toNumber(
    (callData.call_cost as { combined_cost?: number } | undefined)?.combined_cost,
  )
  if (retellFallback != null) return { total: retellFallback / 100, unit: 'usd' }

  return null
}

export function formatProviderCostAmount(value: number, unit: ProviderCostUnit): string {
  if (unit === 'credits') return `${Math.round(value).toLocaleString()} credits`
  return `$${value.toFixed(4)}`
}
