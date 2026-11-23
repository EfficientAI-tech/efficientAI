import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ChevronLeft, Lock, Plus, Swords, Trash2, X } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { isChatMedium } from '../../lib/agentMedium'
import Button from '../../components/Button'
import EvaluatorLlmPicker from '../evaluators/components/EvaluatorLlmPicker'
import type { ModelProvider } from '../../types/api'
import type {
  RedTeamFamily,
  RedTeamIntensity,
  RedTeamLaunchResponse,
  RedTeamPreset,
  RedTeamRun,
  RedTeamRunCreate,
} from '../../types/redTeam'
import { INTENSITY_LABELS, humanizeId } from './redTeamFormat'

type ModalTab = 'intensity' | 'knowledge' | 'connection'

const TABS: { id: ModalTab; label: string }[] = [
  { id: 'intensity', label: 'Intensity' },
  { id: 'knowledge', label: 'Attacker knowledge' },
  { id: 'connection', label: 'Connection' },
]

const INTENSITY_ORDER: RedTeamIntensity[] = ['quick', 'standard', 'thorough', 'custom']

const INTENSITY_BLURBS: Record<RedTeamIntensity, string> = {
  quick: 'Smoke test while iterating on the prompt.',
  standard: 'Balanced coverage of every attack family.',
  thorough: 'Deepest escalation. Use this for the report you share.',
  custom: 'Pick how many attacks each family gets.',
}

interface KnowledgeRow {
  key: number
  label: string
  value: string
}

interface Props {
  isOpen: boolean
  onClose: () => void
  agent: { id: string; name: string; call_medium?: string | null }
  onLaunched: (run: RedTeamRun) => void
}

/** Backend errors: string detail, or `{error, message}` objects (403 enterprise gate). */
function launchErrorMessage(err: unknown): string {
  const response = (err as { response?: { status?: number; data?: { detail?: unknown } } })?.response
  const detail = response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    const obj = detail as { error?: string; message?: string }
    if (obj.error === 'enterprise_feature_required') {
      return obj.message || 'Custom intensity is an Enterprise feature.'
    }
    if (obj.message) return obj.message
  }
  if (response?.status === 403) return 'You do not have access to launch this red team run.'
  return 'Failed to launch red team run'
}

function presetSummary(preset?: RedTeamPreset): string | null {
  if (!preset) return null
  return `${preset.recon_count} recon · up to ${preset.max_attacks} attacks · ${preset.max_levels} levels`
}

export default function LaunchRedTeamModal({ isOpen, onClose, agent, onLaunched }: Props) {
  const [tab, setTab] = useState<ModalTab>('intensity')
  const [intensity, setIntensity] = useState<RedTeamIntensity>('standard')
  const [name, setName] = useState('')
  const [quotas, setQuotas] = useState<Record<string, number>>({})
  const [knowledge, setKnowledge] = useState<KnowledgeRow[]>([])
  const [nextKey, setNextKey] = useState(1)
  const [extension, setExtension] = useState('')
  const [overrideAttacker, setOverrideAttacker] = useState(false)
  const [attackerProvider, setAttackerProvider] = useState<ModelProvider | null>(null)
  const [attackerModel, setAttackerModel] = useState('')
  const [overrideJudge, setOverrideJudge] = useState(false)
  const [judgeProvider, setJudgeProvider] = useState<ModelProvider | null>(null)
  const [judgeModel, setJudgeModel] = useState('')
  const [preview, setPreview] = useState<RedTeamLaunchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const chatAgent = isChatMedium(agent.call_medium)

  const { data: entitlements, isLoading: entitlementsLoading } = useQuery({
    queryKey: ['red-team-entitlements'],
    queryFn: () => apiClient.redTeam.getEntitlements(),
    enabled: isOpen,
    staleTime: 5 * 60 * 1000,
  })

  const maxQuota = entitlements?.max_family_quota ?? 20
  const families: RedTeamFamily[] = useMemo(
    () => (entitlements?.catalog.families ?? []).filter((f) => (chatAgent ? f.chat : f.chat || f.voice)),
    [entitlements, chatAgent],
  )

  // Seed custom quotas from the Standard preset so Custom starts from something sensible.
  useEffect(() => {
    if (!entitlements || Object.keys(quotas).length) return
    const seed = entitlements.presets.standard?.attack_quotas ?? {}
    const next: Record<string, number> = {}
    for (const f of entitlements.catalog.families) next[f.id] = Math.min(maxQuota, seed[f.id] ?? 0)
    setQuotas(next)
  }, [entitlements, maxQuota, quotas])

  useEffect(() => {
    if (!entitlements) return
    if (!entitlements.intensities.includes(intensity)) {
      setIntensity(entitlements.intensities.includes('standard') ? 'standard' : (entitlements.intensities[0] as RedTeamIntensity))
    }
  }, [entitlements, intensity])

  const payload = useMemo((): Omit<RedTeamRunCreate, 'confirmed'> => {
    const attackerKnowledge = knowledge
      .map((k) => ({ label: k.label.trim(), value: k.value.trim() }))
      .filter((k) => k.label && k.value)
    const familyIds = new Set(families.map((f) => f.id))
    return {
      agent_id: agent.id,
      intensity,
      name: name.trim() || null,
      attack_quotas:
        intensity === 'custom'
          ? Object.fromEntries(Object.entries(quotas).filter(([id, n]) => familyIds.has(id) && n > 0))
          : undefined,
      attacker_knowledge: attackerKnowledge,
      connection_overrides: extension.trim() ? { extension: extension.trim() } : undefined,
      attacker_llm_provider: overrideAttacker && attackerModel.trim() ? attackerProvider : null,
      attacker_llm_model: overrideAttacker ? attackerModel.trim() || null : null,
      judge_llm_provider: overrideJudge && judgeModel.trim() ? judgeProvider : null,
      judge_llm_model: overrideJudge ? judgeModel.trim() || null : null,
    }
  }, [
    agent.id,
    intensity,
    name,
    quotas,
    families,
    knowledge,
    extension,
    overrideAttacker,
    attackerProvider,
    attackerModel,
    overrideJudge,
    judgeProvider,
    judgeModel,
  ])

  // Any edit invalidates a preview the user has not confirmed yet.
  useEffect(() => {
    setPreview(null)
  }, [payload])

  useEffect(() => {
    if (!isOpen) {
      setPreview(null)
      setError(null)
    }
  }, [isOpen])

  const launchMutation = useMutation({
    mutationFn: (confirmed: boolean) => apiClient.redTeam.launchRun({ ...payload, confirmed }),
    onSuccess: (data) => {
      if (data.run && !data.needs_confirmation) {
        onLaunched(data.run)
        return
      }
      setPreview(data)
    },
    onError: (err) => setError(launchErrorMessage(err)),
  })

  if (!isOpen) return null

  const customAllowed = entitlements?.custom_allowed ?? false
  const customValid = intensity !== 'custom' || families.some((f) => (quotas[f.id] ?? 0) > 0)
  const overridesValid =
    (!overrideAttacker || Boolean(attackerProvider && attackerModel.trim())) &&
    (!overrideJudge || Boolean(judgeProvider && judgeModel.trim()))
  const canLaunch = Boolean(entitlements) && customValid && overridesValid && !launchMutation.isPending

  const launch = (confirmed: boolean) => {
    setError(null)
    launchMutation.mutate(confirmed)
  }

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-gray-500 bg-opacity-75 p-4">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Launch red team</h3>
            <p className="text-xs text-gray-500">Adversarial callers against {agent.name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>

        {preview ? null : (
          <nav className="-mb-px flex space-x-6 border-b border-gray-200 px-5" aria-label="Launch red team tabs">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={`whitespace-nowrap border-b-2 px-1 py-2.5 text-sm font-medium transition-colors ${
                  tab === t.id
                    ? 'border-primary-500 text-primary-600'
                    : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
        )}

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {entitlementsLoading ? <p className="text-sm text-gray-500">Loading red team options…</p> : null}

          {preview ? (
            <PreviewPanel preview={preview} families={entitlements?.catalog.families ?? []} />
          ) : entitlements && tab === 'intensity' ? (
            <div className="space-y-5">
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  Name <span className="text-gray-400">(optional)</span>
                </label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={200}
                  placeholder="e.g. Pre-launch audit, prompt v4"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {INTENSITY_ORDER.map((id) => {
                  const offered = id === 'custom' || entitlements.intensities.includes(id)
                  const locked = id === 'custom' && !customAllowed
                  const disabled = !offered || locked
                  const selected = intensity === id
                  return (
                    <button
                      key={id}
                      type="button"
                      disabled={disabled}
                      onClick={() => setIntensity(id)}
                      className={`rounded-lg border px-4 py-3 text-left transition-colors ${
                        selected
                          ? 'border-primary-500 bg-primary-50 ring-1 ring-primary-500'
                          : 'border-gray-200 bg-white hover:border-gray-300'
                      } ${disabled ? 'cursor-not-allowed opacity-60 hover:border-gray-200' : ''}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold text-gray-900">{INTENSITY_LABELS[id]}</span>
                        {locked ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
                            <Lock className="h-3 w-3" /> Enterprise
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-0.5 text-xs text-gray-600">{INTENSITY_BLURBS[id]}</p>
                      {id !== 'custom' ? (
                        <p className="mt-1 text-[11px] text-gray-500">{presetSummary(entitlements.presets[id])}</p>
                      ) : null}
                    </button>
                  )
                })}
              </div>

              {intensity === 'custom' ? (
                <div className="rounded-lg border border-gray-200">
                  <div className="border-b border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600">
                    Attacks per family (0–{maxQuota}). Set at least one family above 0.
                    {!chatAgent ? ' Families that do not apply to the agent are ignored.' : ''}
                  </div>
                  <ul className="divide-y divide-gray-100">
                    {families.map((f) => (
                      <li key={f.id} className="flex items-center justify-between gap-4 px-3 py-2">
                        <div className="min-w-0">
                          <div className="text-sm font-medium text-gray-900">
                            {f.name}
                            {f.chat !== f.voice ? (
                              <span className="ml-2 text-[11px] font-normal text-gray-500">
                                {f.chat ? 'chat only' : 'voice only'}
                              </span>
                            ) : null}
                          </div>
                          <p className="text-xs text-gray-500">{f.description}</p>
                        </div>
                        <input
                          type="number"
                          min={0}
                          max={maxQuota}
                          value={quotas[f.id] ?? 0}
                          aria-label={`${f.name} attacks`}
                          onChange={(e) =>
                            setQuotas((prev) => ({
                              ...prev,
                              [f.id]: Math.min(maxQuota, Math.max(0, Math.floor(Number(e.target.value) || 0))),
                            }))
                          }
                          className="w-20 rounded-lg border border-gray-300 px-2 py-1.5 text-right text-sm tabular-nums"
                        />
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : entitlements && tab === 'knowledge' ? (
            <div className="space-y-3">
              <p className="text-sm text-gray-600">
                Facts the attacker may already know about the victim, such as their date of birth or the last 4
                digits of their card. Only social engineering callers use this.
              </p>
              {knowledge.length === 0 ? (
                <p className="rounded-lg border border-dashed border-gray-300 px-3 py-4 text-center text-sm text-gray-500">
                  No attacker knowledge. Callers start with nothing but what recon learns.
                </p>
              ) : (
                <ul className="space-y-2">
                  {knowledge.map((row) => (
                    <li key={row.key} className="flex items-center gap-2">
                      <input
                        value={row.label}
                        placeholder="Label, e.g. Date of birth"
                        aria-label="Knowledge label"
                        onChange={(e) =>
                          setKnowledge((prev) => prev.map((k) => (k.key === row.key ? { ...k, label: e.target.value } : k)))
                        }
                        className="w-2/5 rounded-lg border border-gray-300 px-3 py-2 text-sm"
                      />
                      <input
                        value={row.value}
                        placeholder="Value, e.g. 14 March 1987"
                        aria-label="Knowledge value"
                        onChange={(e) =>
                          setKnowledge((prev) => prev.map((k) => (k.key === row.key ? { ...k, value: e.target.value } : k)))
                        }
                        className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm"
                      />
                      <button
                        type="button"
                        title="Remove"
                        onClick={() => setKnowledge((prev) => prev.filter((k) => k.key !== row.key))}
                        className="rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-700"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <Button
                variant="outline"
                size="sm"
                leftIcon={<Plus className="h-4 w-4" />}
                onClick={() => {
                  setKnowledge((prev) => [...prev, { key: nextKey, label: '', value: '' }])
                  setNextKey((n) => n + 1)
                }}
              >
                Add fact
              </Button>
            </div>
          ) : entitlements && tab === 'connection' ? (
            <div className="space-y-5">
              <label className="block text-sm">
                <span className="mb-1 block font-medium text-gray-700">
                  Extension <span className="text-gray-400">(optional)</span>
                </span>
                <input
                  value={extension}
                  onChange={(e) => setExtension(e.target.value)}
                  placeholder="e.g. 204"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                />
                <span className="mt-1 block text-xs text-gray-500">
                  {chatAgent
                    ? 'Only used for voice agents reached through a phone extension.'
                    : 'Dialed after the call connects when the agent sits behind an extension.'}
                </span>
              </label>
              <div className="space-y-3">
                <label className="flex items-center gap-2 text-sm text-gray-700">
                  <input type="checkbox" checked={overrideAttacker} onChange={(e) => setOverrideAttacker(e.target.checked)} />
                  Override attacker LLM
                </label>
                {overrideAttacker ? (
                  <EvaluatorLlmPicker
                    title="Attacker LLM"
                    description="Model that plays the adversarial caller."
                    llmProvider={attackerProvider}
                    llmModel={attackerModel}
                    onProviderChange={setAttackerProvider}
                    onModelChange={setAttackerModel}
                  />
                ) : null}
                <label className="flex items-center gap-2 text-sm text-gray-700">
                  <input type="checkbox" checked={overrideJudge} onChange={(e) => setOverrideJudge(e.target.checked)} />
                  Override judge LLM
                </label>
                {overrideJudge ? (
                  <EvaluatorLlmPicker
                    title="Judge LLM"
                    description="Model that decides whether each attack breached the agent."
                    llmProvider={judgeProvider}
                    llmModel={judgeModel}
                    onProviderChange={setJudgeProvider}
                    onModelChange={setJudgeModel}
                  />
                ) : null}
              </div>
            </div>
          ) : null}

          {error ? <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p> : null}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-gray-200 px-5 py-4">
          <Button
            variant="outline"
            onClick={() => (preview ? setPreview(null) : onClose())}
            leftIcon={preview ? <ChevronLeft className="h-4 w-4" /> : undefined}
          >
            {preview ? 'Back' : 'Cancel'}
          </Button>
          {preview ? (
            <Button
              variant="primary"
              onClick={() => launch(true)}
              isLoading={launchMutation.isPending}
              leftIcon={<Swords className="h-4 w-4" />}
            >
              Confirm and launch
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={() => launch(false)}
              disabled={!canLaunch}
              isLoading={launchMutation.isPending}
              title={!customValid ? 'Set at least one family above 0' : undefined}
            >
              Launch
            </Button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}

function PreviewPanel({ preview, families }: { preview: RedTeamLaunchResponse; families: RedTeamFamily[] }) {
  const p = preview.preview
  const nameById = new Map(families.map((f) => [f.id, f.name]))
  const voice = preview.modality === 'voice'
  const tiles: { label: string; value: string; hint?: string }[] = [
    { label: 'Recon conversations', value: String(p.recon_conversations) },
    { label: 'Attack conversations', value: `≤ ${p.max_attack_conversations}`, hint: `across ${p.max_levels} levels` },
    { label: 'Total conversations', value: `≤ ${p.max_total_conversations}` },
  ]
  if (p.max_turns_per_conversation) {
    tiles.push({ label: 'Turns per conversation', value: `≤ ${p.max_turns_per_conversation}` })
  }
  if (voice) {
    tiles.push({
      label: 'Voice minutes',
      value: p.max_voice_minutes != null ? `≤ ${p.max_voice_minutes}` : '—',
      hint: p.max_minutes_per_call ? `up to ${p.max_minutes_per_call} min per call` : undefined,
    })
  }
  return (
    <div className="space-y-4">
      <div>
        <h4 className="text-sm font-semibold text-gray-900">Review before launching</h4>
        <p className="mt-0.5 text-sm text-gray-600">
          This {voice ? 'voice' : 'chat'} red team runs up to the limits below. Attacks that make progress spawn
          refined follow-ups, so the real count is often lower.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-lg border border-gray-200 bg-white px-4 py-3">
            <div className="text-xs font-medium text-gray-500">{t.label}</div>
            <div className="mt-1 text-xl font-semibold tabular-nums text-gray-900">{t.value}</div>
            {t.hint ? <div className="mt-0.5 text-xs text-gray-500">{t.hint}</div> : null}
          </div>
        ))}
      </div>
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
        <div className="mb-2 text-xs font-medium text-gray-500">Starting attacks per family</div>
        <ul className="grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">
          {Object.entries(p.attack_quotas).map(([id, n]) => (
            <li key={id} className="flex justify-between gap-3">
              <span className="text-gray-700">{nameById.get(id) ?? humanizeId(id)}</span>
              <span className="tabular-nums font-medium text-gray-900">{n}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
