export type MetricSurface = 'agent' | 'voice_playground' | 'blind_test'

export type ClassificationChoiceOption = {
  local_id: string
  label: string
  description: string
}

export type ClassificationFormState = {
  name: string
  description: string
  surfaces: MetricSurface[]
  enabled: boolean
  scope: 'workspace' | 'organization'
  noul: {
    enabled: boolean
    instructions: string
    trueCriteria: string
    falseCriteria: string
  }
  choice: {
    enabled: boolean
    instructions: string
    options: ClassificationChoiceOption[]
  }
  score: {
    enabled: boolean
    instructions: string
    levels: string[]
  }
}

export function defaultClassificationForm(): ClassificationFormState {
  return {
    name: '',
    description: '',
    surfaces: ['agent'],
    enabled: true,
    scope: 'workspace',
    noul: {
      enabled: false,
      instructions: '',
      trueCriteria: '',
      falseCriteria: '',
    },
    choice: {
      enabled: false,
      instructions: '',
      options: [
        { local_id: 'opt-other', label: 'other', description: 'None of the above' },
        { local_id: 'opt-1', label: '', description: '' },
      ],
    },
    score: {
      enabled: false,
      instructions: '',
      levels: ['Low', 'High'],
    },
  }
}

type MetricLike = {
  name: string
  description?: string | null
  supported_surfaces?: string[] | null
  enabled?: boolean
  scope?: 'workspace' | 'organization'
  workspace_id?: string | null
  custom_config?: Record<string, unknown> | null
}

export function classificationFormFromMetric(metric: MetricLike): ClassificationFormState {
  const cfg = (metric.custom_config || {}) as Record<string, any>
  const noulCfg = cfg.noul || {}
  const choiceCfg = cfg.choice || {}
  const scoreCfg = cfg.score || {}

  const choiceCriteria = choiceCfg.criteria
  const choiceOptions: ClassificationChoiceOption[] =
    choiceCriteria && typeof choiceCriteria === 'object' && !Array.isArray(choiceCriteria)
      ? Object.entries(choiceCriteria as Record<string, string>).map(([label, description], i) => ({
          local_id: `opt-${i}`,
          label,
          description: String(description || ''),
        }))
      : defaultClassificationForm().choice.options

  const scoreLevels = Array.isArray(scoreCfg.criteria)
    ? scoreCfg.criteria.map(String)
    : defaultClassificationForm().score.levels

  const noulCriteria = noulCfg.criteria || {}

  return {
    name: metric.name,
    description: metric.description || '',
    surfaces: (metric.supported_surfaces?.length
      ? metric.supported_surfaces
      : ['agent']) as MetricSurface[],
    enabled: metric.enabled !== false,
    scope:
      metric.scope ||
      (metric.workspace_id == null ? 'organization' : 'workspace'),
    noul: {
      enabled: !!noulCfg.enabled,
      instructions: String(noulCfg.instructions || ''),
      trueCriteria: String(noulCriteria.true || ''),
      falseCriteria: String(noulCriteria.false || ''),
    },
    choice: {
      enabled: !!choiceCfg.enabled,
      instructions: String(choiceCfg.instructions || ''),
      options: choiceOptions.length >= 2 ? choiceOptions : defaultClassificationForm().choice.options,
    },
    score: {
      enabled: !!scoreCfg.enabled,
      instructions: String(scoreCfg.instructions || ''),
      levels: scoreLevels.length >= 2 ? scoreLevels : defaultClassificationForm().score.levels,
    },
  }
}

export function buildClassificationCustomConfig(form: ClassificationFormState) {
  const config: Record<string, unknown> = {
    noul: { enabled: form.noul.enabled },
    choice: { enabled: form.choice.enabled },
    score: { enabled: form.score.enabled },
  }

  if (form.noul.enabled) {
    config.noul = {
      enabled: true,
      instructions: form.noul.instructions.trim(),
      criteria: {
        true: form.noul.trueCriteria.trim(),
        false: form.noul.falseCriteria.trim(),
      },
    }
  }
  if (form.choice.enabled) {
    const criteria: Record<string, string> = {}
    for (const opt of form.choice.options) {
      const label = opt.label.trim()
      const desc = opt.description.trim()
      if (label && desc) {
        criteria[label] = desc
      }
    }
    config.choice = {
      enabled: true,
      instructions: form.choice.instructions.trim(),
      criteria,
    }
  }
  if (form.score.enabled) {
    config.score = {
      enabled: true,
      instructions: form.score.instructions.trim(),
      criteria: form.score.levels.map((l) => l.trim()).filter(Boolean),
    }
  }

  return config
}

export function validateClassificationForm(form: ClassificationFormState): string | null {
  if (!form.name.trim()) {
    return 'Please enter a metric name'
  }
  const enabled =
    form.noul.enabled || form.choice.enabled || form.score.enabled
  if (!enabled) {
    return 'Enable at least one of Noul, Choice, or Score'
  }
  if (form.noul.enabled) {
    if (!form.noul.instructions.trim()) {
      return 'Noul requires instructions'
    }
    if (!form.noul.trueCriteria.trim() || !form.noul.falseCriteria.trim()) {
      return 'Noul requires criteria for both true and false'
    }
  }
  if (form.choice.enabled) {
    if (!form.choice.instructions.trim()) {
      return 'Choice requires instructions'
    }
    const filled = form.choice.options.filter(
      (o) => o.label.trim() && o.description.trim(),
    )
    if (filled.length < 2) {
      return 'Choice requires at least two options with label and description'
    }
  }
  if (form.score.enabled) {
    if (!form.score.instructions.trim()) {
      return 'Score requires instructions'
    }
    const levels = form.score.levels.map((l) => l.trim()).filter(Boolean)
    if (levels.length < 2) {
      return 'Score requires at least two ordered levels'
    }
  }
  return null
}

export function buildClassificationPayload(
  form: ClassificationFormState,
  editing: boolean,
) {
  return {
    name: form.name.trim(),
    description: form.description.trim() || undefined,
    metric_type: 'text' as const,
    metric_origin: 'custom' as const,
    trigger: 'always' as const,
    enabled: form.enabled,
    supported_surfaces: form.surfaces,
    enabled_surfaces: form.enabled ? form.surfaces : [],
    custom_data_type: 'classification' as const,
    custom_config: buildClassificationCustomConfig(form),
    capture_rationale: false,
    compare_transcripts: false,
    ...(!editing ? { scope: form.scope } : {}),
  }
}
