/** Best-effort tokens / cost for Results hub per-run tables (provider call_data + usage blobs). */

import { extractProviderCostSummary } from '../../../lib/voiceProviderMetrics'

function asInt(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return Math.round(value)
  if (typeof value === 'string' && value.trim()) {
    const n = Number(value)
    return Number.isFinite(n) ? Math.round(n) : 0
  }
  return 0
}

function asUsd(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const n = Number(value)
    return Number.isFinite(n) ? n : 0
  }
  return 0
}

function pick(...values: unknown[]): unknown {
  for (const value of values) {
    if (value != null && value !== '') return value
  }
  return undefined
}

function tokensFromLlmUsageBlock(block: Record<string, unknown> | undefined): number {
  if (!block) return 0
  const direct = asInt(pick(block.total_tokens, block.totalTokens))
  if (direct > 0) return direct
  const prompt = asInt(
    pick(block.prompt_tokens, block.input_tokens, block.llm_prompt_tokens),
  )
  const completion = asInt(
    pick(block.completion_tokens, block.output_tokens, block.llm_completion_tokens),
  )
  if (prompt > 0 || completion > 0) return prompt + completion
  const values = block.values
  if (Array.isArray(values)) {
    const sum = values.reduce((acc, v) => acc + asInt(v), 0)
    if (sum > 0) return sum
  }
  return 0
}

type UsageByModelRow = { total_tokens?: number; total_cost_usd?: number }

function usageFromModelLedger(
  byModel: Record<string, UsageByModelRow> | undefined,
  focusModel?: string | null,
): { tokens: number; costUsd: number; model: string } | null {
  if (!byModel || typeof byModel !== 'object') return null
  if (focusModel) {
    const direct = byModel[focusModel]
    if (direct) {
      return {
        tokens: asInt(direct.total_tokens),
        costUsd: asUsd(direct.total_cost_usd),
        model: focusModel,
      }
    }
    const needle = focusModel.trim().toLowerCase()
    const match = Object.entries(byModel).find(([name]) => name.trim().toLowerCase() === needle)
    if (match) {
      const [, row] = match
      return {
        tokens: asInt(row.total_tokens),
        costUsd: asUsd(row.total_cost_usd),
        model: match[0],
      }
    }
    return null
  }
  let tokens = 0
  let costUsd = 0
  let model = ''
  let bestCost = 0
  for (const [name, row] of Object.entries(byModel)) {
    const rowTokens = asInt(row.total_tokens)
    const rowCost = asUsd(row.total_cost_usd)
    tokens += rowTokens
    costUsd += rowCost
    if (rowCost > bestCost) {
      bestCost = rowCost
      model = name
    }
  }
  if (!tokens && !costUsd) return null
  return { tokens, costUsd, model }
}

type UsageByRoleRow = { total_tokens?: number; total_cost_usd?: number }

export function usageFromEvaluatorCallData(
  callData: Record<string, unknown> | null | undefined,
  providerPlatform?: string | null,
  focusModel?: string | null,
  focusRole?: string | null,
): { tokens: number; costUsd: number; model: string } {
  if (focusRole) {
    const byRole = callData?.usage_by_role as Record<string, UsageByRoleRow> | undefined
    const slice = byRole?.[focusRole]
    if (slice) {
      return {
        tokens: asInt(slice.total_tokens),
        costUsd: asUsd(slice.total_cost_usd),
        model: focusModel ?? '',
      }
    }
    if (focusModel) {
      return { tokens: 0, costUsd: 0, model: focusModel }
    }
  }
  if (!callData || typeof callData !== 'object') {
    return { tokens: 0, costUsd: 0, model: '' }
  }

  const ledger = usageFromModelLedger(
    callData.usage_by_model as Record<string, UsageByModelRow> | undefined,
    focusModel,
  )
  if (ledger) return ledger
  if (focusModel) {
    return { tokens: 0, costUsd: 0, model: focusModel }
  }

  const platform = String(
    providerPlatform ?? callData.provider_platform ?? callData.platform ?? '',
  ).toLowerCase()

  let tokens = 0
  let costUsd = 0
  let model = String(pick(callData.model, callData.llm_model) ?? '')

  const usage = callData.usage
  if (usage && typeof usage === 'object') {
    tokens = tokensFromLlmUsageBlock(usage as Record<string, unknown>)
    costUsd = asUsd(pick((usage as Record<string, unknown>).total_cost_usd, (usage as Record<string, unknown>).cost_usd))
  }

  const cbRaw = pick(callData.costBreakdown, callData.cost_breakdown)
  const cb =
    cbRaw && typeof cbRaw === 'object' ? (cbRaw as Record<string, unknown>) : undefined
  if (cb) {
    const vapiTokens =
      asInt(pick(cb.llmPromptTokens, cb.llm_prompt_tokens)) +
      asInt(pick(cb.llmCompletionTokens, cb.llm_completion_tokens))
    if (vapiTokens > tokens) tokens = vapiTokens
    if (!costUsd) {
      costUsd = asUsd(
        pick(callData.cost, cb.total, cb.totalCost, cb.total_cost),
      )
    }
    if (!model) {
      const assistant = callData.assistant
      model = String(
        pick(
          callData.model,
          assistant && typeof assistant === 'object'
            ? (assistant as Record<string, unknown>).model
            : undefined,
        ) ?? '',
      )
    }
  }

  if (platform === 'retell' || callData.llm_token_usage) {
    const retellTokens = tokensFromLlmUsageBlock(
      callData.llm_token_usage as Record<string, unknown> | undefined,
    )
    if (retellTokens > tokens) tokens = retellTokens
    const callCost = callData.call_cost
    if (callCost && typeof callCost === 'object') {
      const cc = callCost as Record<string, unknown>
      if (!costUsd) {
        const cents = asUsd(pick(cc.combined_call_cost, cc.total_cost))
        if (cents > 0) costUsd = cents / 100
        else {
          costUsd = asUsd(pick(cc.total_cost_usd, cc.total_cost_dollars))
        }
      }
    }
    if (!model) model = String(pick(callData.llm_model, callData.model) ?? '')
  }

  if (!tokens) {
    tokens = tokensFromLlmUsageBlock(
      callData.llm_token_usage as Record<string, unknown> | undefined,
    )
  }

  if (!costUsd) {
    const summary = extractProviderCostSummary(platform || providerPlatform, callData)
    if (summary?.total) costUsd = summary.total
  }

  if (!tokens) {
    const cb = pick(callData.costBreakdown, callData.cost_breakdown) as Record<string, unknown> | undefined
    if (cb) {
      const vapiTokens =
        asInt(pick(cb.llmPromptTokens, cb.llm_prompt_tokens)) +
        asInt(pick(cb.llmCompletionTokens, cb.llm_completion_tokens))
      if (vapiTokens > 0) tokens = vapiTokens
    }
  }

  const metadata = callData.metadata
  if (metadata && typeof metadata === 'object') {
    const meta = metadata as Record<string, unknown>
    if (!costUsd) costUsd = asUsd(meta.cost)
    const charging = meta.charging
    if (charging && typeof charging === 'object') {
      const ch = charging as Record<string, unknown>
      if (!costUsd) {
        costUsd =
          asUsd(ch.llm_charge) + asUsd(ch.call_charge) ||
          asUsd(ch.llm_price)
      }
    }
  }

  if (!tokens && !costUsd) {
    const fallback = usageFromModelLedger(
      callData.usage_by_model as Record<string, UsageByModelRow> | undefined,
    )
    if (fallback) return fallback
  }

  if (!model && platform) model = `${platform}-agent`

  return { tokens, costUsd, model }
}

export function callHasModelUsage(
  callData: Record<string, unknown> | null | undefined,
  model: string,
): boolean {
  const byModel = callData?.usage_by_model as Record<string, UsageByModelRow> | undefined
  if (byModel?.[model]) {
    const row = byModel[model]
    return asInt(row.total_tokens) > 0 || asUsd(row.total_cost_usd) > 0
  }
  return usageFromEvaluatorCallData(callData, undefined, model).costUsd > 0
    || usageFromEvaluatorCallData(callData, undefined, model).tokens > 0
}