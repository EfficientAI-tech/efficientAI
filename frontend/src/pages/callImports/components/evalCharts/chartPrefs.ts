import type { CallImportMetricAggregate } from '../../../../types/api'

export const PIE_COLORS = [
  '#6366f1',
  '#10b981',
  '#f59e0b',
  '#ef4444',
  '#a855f7',
  '#0ea5e9',
  '#ec4899',
  '#14b8a6',
  '#f97316',
  '#84cc16',
]

// All categorical chart types the Visualizations tab can render. Each
// type has a corresponding icon shown in the per-metric chart picker
// and the global default selector. Multi-label-only types (heatmap /
// coverage) are still in the union — the picker just hides them for
// non-multi-label metrics.
export type CategoricalChartType =
  | 'pie'
  | 'bar'
  | 'lollipop'
  | 'radial'
  | 'treemap'
  | 'waffle'
  | 'heatmap'
  | 'coverage'

// "auto" lets us pick the best fit per metric (numeric → histogram,
// few categories → radial, more → lollipop, lots → treemap). When the
// user picks an explicit chart type at the global level, every
// non-overridden categorical metric uses that type instead of the
// per-metric auto pick.
export type CategoricalChartChoice = 'auto' | CategoricalChartType

const CHART_PREFS_KEY = 'callImportEval.chartPrefs.v1'
const CHART_GLOBAL_DEFAULT_KEY = 'callImportEval.chartGlobalDefault.v1'

export function loadChartGlobalDefault(): CategoricalChartChoice {
  if (typeof window === 'undefined') return 'auto'
  try {
    const raw = window.localStorage.getItem(CHART_GLOBAL_DEFAULT_KEY)
    if (!raw) return 'auto'
    return JSON.parse(raw) as CategoricalChartChoice
  } catch {
    return 'auto'
  }
}

export function saveChartGlobalDefault(value: CategoricalChartChoice): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(
      CHART_GLOBAL_DEFAULT_KEY,
      JSON.stringify(value),
    )
  } catch {
    /* ignore quota / privacy-mode errors */
  }
}

export function loadChartPerMetric(): Record<string, CategoricalChartType> {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(CHART_PREFS_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

export function saveChartPerMetric(
  value: Record<string, CategoricalChartType>,
): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(CHART_PREFS_KEY, JSON.stringify(value))
  } catch {
    /* ignore quota / privacy-mode errors */
  }
}

/**
 * Pick the best-fitting chart type for a categorical metric when the
 * user hasn't explicitly chosen one. Defaults to a ranked lollipop
 * for everything because it scales cleanly from 2 to ~12 categories,
 * never overlaps labels, and reads as a sorted top-N list at a
 * glance. Truly wide categorical sets (>12 unique values) graduate
 * to a treemap so the lollipop's vertical run doesn't get unwieldy.
 */
export function autoPickCategoricalChart(
  metric: CallImportMetricAggregate,
): CategoricalChartType {
  const n = metric.value_counts.length
  if (n > 12) return 'treemap'
  return 'lollipop'
}

/**
 * Resolve the chart type the renderer should use for a given metric,
 * combining (in priority order): per-metric override → global default
 * (when set to a concrete type) → auto pick by cardinality.
 */
export function resolveCategoricalChart(
  metric: CallImportMetricAggregate,
  perMetric: Record<string, CategoricalChartType>,
  globalDefault: CategoricalChartChoice,
): CategoricalChartType {
  const override = perMetric[metric.metric_id]
  if (override) return override
  if (globalDefault !== 'auto') {
    if (
      metric.is_multi_label_parent &&
      (globalDefault === 'pie' ||
        globalDefault === 'radial' ||
        globalDefault === 'waffle')
    ) {
      return 'bar'
    }
    if (
      !metric.is_multi_label_parent &&
      (globalDefault === 'heatmap' || globalDefault === 'coverage')
    ) {
      return autoPickCategoricalChart(metric)
    }
    return globalDefault
  }
  return autoPickCategoricalChart(metric)
}
