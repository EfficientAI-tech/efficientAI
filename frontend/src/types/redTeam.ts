// Red teaming (EFF-125): adversarial simulated callers attacking an agent.

export type RedTeamIntensity = 'quick' | 'standard' | 'thorough' | 'custom'
export type RedTeamPresetIntensity = Exclude<RedTeamIntensity, 'custom'>
export type RedTeamModality = 'chat' | 'voice'
export type RedTeamFamilyId =
  | 'social_engineering'
  | 'prompt_injection'
  | 'text_native'
  | 'audio_native'
  | 'content_harm'

export type RedTeamRunStatus =
  | 'queued'
  | 'recon'
  | 'attacking'
  | 'reporting'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type RedTeamVerdict = 'breached' | 'held_under_pressure' | 'held' | 'inconclusive'
export type RedTeamAttackStatus = 'queued' | 'running' | 'evaluating' | 'completed' | 'failed' | 'cancelled'
export type RedTeamOutcome = 'breached' | 'conceded' | 'held' | 'error'
export type RedTeamCategoryStatus = 'FAIL' | 'PARTIAL' | 'PASS' | 'NOT_TESTED'

export interface RedTeamPreset {
  recon_count: number
  max_levels: number
  max_branches: number
  max_turns: number
  max_call_minutes: number
  n_concurrent: number
  attack_quotas: Record<string, number>
  max_attacks: number
}

export interface RedTeamFamily {
  id: string
  name: string
  description: string
  chat: boolean
  voice: boolean
}

export interface RedTeamCatalog {
  version: string
  families: RedTeamFamily[]
  owasp_categories: { id: string; name: string }[]
  harm_categories: { id: string; name: string }[]
  techniques: {
    id: string
    family: string
    name: string
    goal: string
    owasp?: string | null
    harm?: string | null
  }[]
}

export interface RedTeamEntitlements {
  intensities: string[]
  custom_allowed: boolean
  max_family_quota: number
  presets: Partial<Record<RedTeamPresetIntensity, RedTeamPreset>>
  catalog: RedTeamCatalog
}

export interface RedTeamKnowledgeItem {
  label: string
  value: string
}

export interface RedTeamRunCreate {
  agent_id: string
  intensity: RedTeamIntensity
  name?: string | null
  attack_quotas?: Record<string, number>
  attacker_knowledge: RedTeamKnowledgeItem[]
  connection_overrides?: { extension?: string }
  persona_id?: string | null
  attacker_llm_provider?: string | null
  attacker_llm_model?: string | null
  judge_llm_provider?: string | null
  judge_llm_model?: string | null
  confirmed: boolean
}

export interface RedTeamPreview {
  recon_conversations: number
  max_attack_conversations: number
  max_total_conversations: number
  max_levels: number
  attack_quotas: Record<string, number>
  max_minutes_per_call?: number | null
  max_voice_minutes?: number | null
  max_turns_per_conversation?: number | null
}

export interface RedTeamAgentProfile {
  summary?: string | null
  data_held?: string[]
  gated_actions?: string[]
  verification_steps?: string[]
  refused_topics?: string[]
  tools?: string[]
}

export interface RedTeamReportCategory {
  id: string
  kind: 'owasp' | 'harm'
  name: string
  status: RedTeamCategoryStatus
  attacks: number
  breached: number
  conceded: number
  held: number
  max_success_score: number | null
}

export interface RedTeamReportFamily {
  id: string
  name: string
  quota: number
  attempts: number
  breached: number
  conceded: number
}

export interface RedTeamReport {
  verdict: RedTeamVerdict
  passed: boolean
  totals: { attacks: number; breached: number; conceded: number; held: number; errors: number; recon: number }
  categories: RedTeamReportCategory[]
  families: RedTeamReportFamily[]
  breached_attack_ids: string[]
  conceded_attack_ids: string[]
  not_assessed: string[]
  content_harm_failed: boolean
  generated_at?: string | null
}

export interface RedTeamRun {
  id: string
  run_id: string
  agent_id: string
  name: string | null
  intensity: RedTeamIntensity
  modality: RedTeamModality
  config: Record<string, unknown> | null
  attacker_knowledge: RedTeamKnowledgeItem[] | null
  connection_overrides: { extension?: string } | null
  persona_id: string | null
  resolved_llms: Record<string, { label?: string | null; source_label?: string | null } | null> | null
  catalog_version: string | null
  agent_profile: RedTeamAgentProfile | null
  status: RedTeamRunStatus
  verdict: RedTeamVerdict | null
  report: RedTeamReport | null
  max_attacks: number
  completed_attacks: number
  breached_attacks: number
  error_message: string | null
  cancel_requested: boolean
  started_at: string | null
  finished_at: string | null
  created_at: string
  created_by?: string | null
}

export interface RedTeamLaunchResponse {
  needs_confirmation: boolean
  modality: RedTeamModality
  config: Record<string, unknown>
  preview: RedTeamPreview
  run: RedTeamRun | null
}

export interface RedTeamAttack {
  id: string
  parent_attack_id: string | null
  kind: 'recon' | 'attack'
  level: number
  sequence: number
  family: string | null
  technique_id: string | null
  technique_name: string | null
  owasp_category: string | null
  harm_category: string | null
  goal: string | null
  strategy: string | null
  status: RedTeamAttackStatus
  outcome: RedTeamOutcome | null
  score: number | null
  success_score: number | null
  rationale: string | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
}

export interface RedTeamRunDetail extends RedTeamRun {
  attacks: RedTeamAttack[]
}

export interface RedTeamJudge {
  outcome: RedTeamOutcome | null
  score: number | null
  rationale: string | null
  evidence_turns: number[]
  leaked_data: string[]
  gated_actions: string[]
  non_refusal?: number | null
  specificity?: number | null
  actionability?: number | null
  success_score?: number | null
}

export interface RedTeamTranscriptTurn {
  role: 'attacker' | 'agent'
  text: string
  tool_calls?: { name?: string; tool?: string; arguments?: unknown; result?: unknown }[] | null
}

export interface RedTeamAttackDetail extends RedTeamAttack {
  judge: RedTeamJudge | null
  transcript: RedTeamTranscriptTurn[]
  evaluator_result_id: string | null
  evaluator_result_ref: string | null
  has_recording: boolean
  redacted: boolean
}
