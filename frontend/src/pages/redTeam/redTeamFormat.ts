import type { RedTeamAttack, RedTeamIntensity, RedTeamRunStatus } from '../../types/redTeam'

export const ACTIVE_RED_TEAM_STATUSES: RedTeamRunStatus[] = ['queued', 'recon', 'attacking', 'reporting']

export function isRedTeamRunActive(status: RedTeamRunStatus): boolean {
  return ACTIVE_RED_TEAM_STATUSES.includes(status)
}

export const INTENSITY_LABELS: Record<RedTeamIntensity, string> = {
  quick: 'Quick',
  standard: 'Standard',
  thorough: 'Thorough',
  custom: 'Custom',
}

export function redTeamRunTitle(run: { name: string | null; run_id: string }): string {
  return run.name || `Red team run ${run.run_id}`
}

/** OWASP id or harm category id for an attack, e.g. "LLM01" or "harm:self_harm". */
export function attackCategoryLabel(attack: Pick<RedTeamAttack, 'owasp_category' | 'harm_category'>): string | null {
  return attack.owasp_category || (attack.harm_category ? attack.harm_category.replace(/^harm:/, '').replace(/_/g, ' ') : null)
}

export function humanizeId(id?: string | null): string {
  if (!id) return '—'
  return id.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}
