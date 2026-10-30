import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, MessageSquare } from 'lucide-react'
import Button from '../../../components/Button'
import type {
  AgentConfig,
  AgentRole,
  Catalog,
  HealthBadge,
  RagAttachment,
  SkillDef,
  ToolDef,
} from '../../../lib/sandbox'
import { HealthBadge as HealthBadgeChip, RoleBadge } from './badges'

function Section({
  title,
  children,
  badges,
  disabled,
  hint,
  defaultOpen = false,
  onHealthClick,
}: {
  title: string
  children: React.ReactNode
  badges?: HealthBadge[]
  disabled?: boolean
  hint?: string
  defaultOpen?: boolean
  onHealthClick?: (badge: HealthBadge) => void
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className={`rounded-lg border border-gray-200 ${disabled ? 'opacity-60' : ''}`}>
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm font-medium text-gray-900"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          {title}
        </button>
        <span className="flex gap-1">
          {badges?.map((badge) => (
            <HealthBadgeChip
              key={badge.itemId + badge.section}
              count={badge.count}
              severity={badge.severity}
              label={badge.label}
              onClick={onHealthClick ? () => onHealthClick(badge) : undefined}
            />
          ))}
        </span>
      </div>
      {hint && <p className="px-3 pb-1 text-[11px] text-gray-500">{hint}</p>}
      {open && <div className="border-t border-gray-100 p-3">{children}</div>}
    </section>
  )
}

export function AgentConfigPanel({
  role,
  config,
  catalog,
  health,
  onChange,
  onTestInChat,
  testDisabledReason,
  primaryTestButton,
  onHealthClick,
}: {
  role: AgentRole
  config: AgentConfig
  catalog: Catalog
  health: HealthBadge[]
  onChange: (next: AgentConfig) => void
  onTestInChat?: () => void
  testDisabledReason?: string
  primaryTestButton?: boolean
  onHealthClick?: (badge: HealthBadge) => void
}) {
  const envTools = catalog.tools
  const healthFor = (section: HealthBadge['section']) => health.filter((h) => h.section === section)

  const loadAgent = (id: string) => {
    const found = catalog.platformAgents.find((a) => a.id === id)
    if (found) onChange({ ...found.config })
  }

  const toggleTool = (tool: ToolDef) => {
    const exists = config.tools.some((t) => t.id === tool.id)
    onChange({
      ...config,
      tools: exists ? config.tools.filter((t) => t.id !== tool.id) : [...config.tools, tool],
    })
  }

  const toggleSkill = (skill: SkillDef) => {
    const exists = config.skills.some((s) => s.id === skill.id)
    onChange({
      ...config,
      skills: exists ? config.skills.filter((s) => s.id !== skill.id) : [...config.skills, skill],
    })
  }

  const toggleRag = (rag: RagAttachment) => {
    const exists = config.rag.some((r) => r.collectionId === rag.collectionId)
    onChange({
      ...config,
      rag: exists ? config.rag.filter((r) => r.collectionId !== rag.collectionId) : [...config.rag, rag],
    })
  }

  const models = useMemo(
    () => catalog.llmOptions.find((o) => o.provider === config.llm.provider)?.models ?? [],
    [catalog, config.llm.provider],
  )

  return (
    <div className="flex h-full flex-col gap-3 rounded-xl border border-gray-200 bg-white p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <RoleBadge role={role} />
          <input
            className="mt-2 w-full rounded border border-gray-300 px-2 py-1 text-sm font-medium"
            value={config.name}
            onChange={(e) => onChange({ ...config, name: e.target.value })}
            placeholder={role === 'A' ? 'Main agent name' : 'Test agent name'}
            aria-label="Agent name"
          />
        </div>
        {onTestInChat &&
          (primaryTestButton ? (
            <Button
              size="sm"
              leftIcon={<MessageSquare className="h-3.5 w-3.5" />}
              onClick={onTestInChat}
              disabled={Boolean(testDisabledReason)}
              title={testDisabledReason}
            >
              Test in chat
            </Button>
          ) : (
            <button
              type="button"
              className="text-xs text-gray-600 underline disabled:opacity-40"
              onClick={onTestInChat}
              disabled={Boolean(testDisabledReason)}
              title={testDisabledReason}
            >
              Test in chat
            </button>
          ))}
      </div>

      <label className="text-xs text-gray-600">
        Load from existing agent
        <select
          className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-sm"
          value={config.platformAgentId ?? ''}
          onChange={(e) => loadAgent(e.target.value)}
        >
          <option value="">Build inline</option>
          {catalog.platformAgents
            .filter((a) => a.role === role || role === 'A')
            .map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
        </select>
      </label>
      {!config.platformAgentId && (
        <p className="text-[11px] text-amber-800">
          This dismissal applies to this chat only until you save the agent.
        </p>
      )}

      <Section title="Prompt" defaultOpen onHealthClick={onHealthClick}>
        <textarea
          className="h-32 w-full rounded border border-gray-300 p-2 text-sm"
          value={config.prompt}
          onChange={(e) => onChange({ ...config, prompt: e.target.value })}
          placeholder="System prompt"
        />
      </Section>

      <Section title="Model stack" defaultOpen badges={healthFor('llm')} onHealthClick={onHealthClick}>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <label>
            Provider
            <select
              className="mt-1 w-full rounded border px-2 py-1"
              value={config.llm.provider}
              onChange={(e) =>
                onChange({
                  ...config,
                  llm: {
                    ...config.llm,
                    provider: e.target.value,
                    model: catalog.llmOptions.find((o) => o.provider === e.target.value)?.models[0] ?? '',
                  },
                })
              }
            >
              {catalog.llmOptions.map((opt) => (
                <option key={opt.provider} value={opt.provider}>
                  {opt.provider}
                </option>
              ))}
            </select>
          </label>
          <label>
            Model
            <select
              className="mt-1 w-full rounded border px-2 py-1"
              value={config.llm.model}
              onChange={(e) => onChange({ ...config, llm: { ...config.llm, model: e.target.value } })}
            >
              {models.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          </label>
          <label>
            Credential
            <input
              className="mt-1 w-full rounded border px-2 py-1"
              value={config.llm.credentialId ?? ''}
              onChange={(e) => onChange({ ...config, llm: { ...config.llm, credentialId: e.target.value } })}
            />
          </label>
          <label>
            Temperature
            <input
              type="number"
              step="0.1"
              className="mt-1 w-full rounded border px-2 py-1"
              value={config.llm.temperature ?? 0.2}
              onChange={(e) =>
                onChange({ ...config, llm: { ...config.llm, temperature: Number(e.target.value) } })
              }
            />
          </label>
          <label>
            Max tokens
            <input
              type="number"
              className="mt-1 w-full rounded border px-2 py-1"
              value={config.llm.maxTokens ?? 1024}
              onChange={(e) =>
                onChange({ ...config, llm: { ...config.llm, maxTokens: Number(e.target.value) } })
              }
            />
          </label>
        </div>
      </Section>

      <Section title="Voice stack" disabled hint="Voice coming soon">
        <div className="grid grid-cols-2 gap-2 text-sm">
          <label>
            STT
            <input disabled className="mt-1 w-full rounded border px-2 py-1" value={config.voice?.stt ?? ''} />
          </label>
          <label>
            TTS
            <input disabled className="mt-1 w-full rounded border px-2 py-1" value={config.voice?.tts ?? ''} />
          </label>
        </div>
      </Section>

      <Section title="Framework" disabled hint="LiveKit and Pipecat are voice-phase">
        <select disabled className="w-full rounded border px-2 py-1 text-sm" value={config.framework}>
          <option value="native">Native (chat)</option>
          <option value="livekit">LiveKit</option>
          <option value="pipecat">Pipecat</option>
        </select>
      </Section>

      <Section title="Tools" badges={healthFor('tools')} onHealthClick={onHealthClick}>
        <ul className="space-y-2 text-sm">
          {envTools.map((tool) => {
            const attached = config.tools.some((t) => t.id === tool.id)
            const badge = health.find((h) => h.section === 'tools' && h.itemId === tool.id)
            return (
              <li key={tool.id} className="rounded border border-gray-100 p-2">
                <label className="flex items-start gap-2">
                  <input type="checkbox" checked={attached} onChange={() => toggleTool(tool)} />
                  <span>
                    <span className="font-medium">{tool.name}</span>{' '}
                    <span className="rounded bg-gray-100 px-1 text-[10px] uppercase">{tool.kind}</span>{' '}
                    <span className="rounded bg-gray-100 px-1 text-[10px] uppercase">{tool.access}</span>
                    {badge && (
                      <span className="ml-2">
                        <HealthBadgeChip count={badge.count} severity={badge.severity} label={badge.label} />
                      </span>
                    )}
                    <p className="text-xs text-gray-500">{tool.description}</p>
                  </span>
                </label>
              </li>
            )
          })}
        </ul>
        {config.tools.length === 0 && <p className="text-xs text-gray-500">No tools attached.</p>}
      </Section>

      <Section title="Skills" badges={healthFor('skills')} onHealthClick={onHealthClick}>
        <ul className="space-y-2 text-sm">
          {catalog.skills.map((skill) => (
            <li key={skill.id}>
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={config.skills.some((s) => s.id === skill.id)}
                  onChange={() => toggleSkill(skill)}
                />
                <span>
                  <span className="font-medium">{skill.name}</span>
                  <p className="text-xs text-gray-500">{skill.markdown}</p>
                </span>
              </label>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Harness" badges={healthFor('harness')} onHealthClick={onHealthClick}>
        <select
          className="w-full rounded border px-2 py-1 text-sm"
          value={config.harness?.id ?? ''}
          onChange={(e) => {
            const found = catalog.harnesses.find((h) => h.id === e.target.value)
            onChange({ ...config, harness: found })
          }}
        >
          {catalog.harnesses.map((h) => (
            <option key={h.id} value={h.id}>
              {h.name}
            </option>
          ))}
        </select>
      </Section>

      <Section title="RAG" badges={healthFor('rag')} onHealthClick={onHealthClick}>
        {catalog.ragCollections.map((rag) => (
          <label key={rag.collectionId} className="mb-2 flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={config.rag.some((r) => r.collectionId === rag.collectionId)}
              onChange={() => toggleRag(rag)}
            />
            <span>
              {rag.name} · {rag.docCount} docs
            </span>
          </label>
        ))}
        {config.rag.map((rag) => (
          <div key={rag.collectionId} className="mt-2 grid grid-cols-2 gap-2 text-xs">
            <label>
              top-k
              <input
                type="number"
                className="mt-1 w-full rounded border px-2 py-1"
                value={rag.topK}
                onChange={(e) =>
                  onChange({
                    ...config,
                    rag: config.rag.map((r) =>
                      r.collectionId === rag.collectionId ? { ...r, topK: Number(e.target.value) } : r,
                    ),
                  })
                }
              />
            </label>
            <label>
              threshold
              <input
                type="number"
                step="0.05"
                className="mt-1 w-full rounded border px-2 py-1"
                value={rag.threshold ?? 0}
                onChange={(e) =>
                  onChange({
                    ...config,
                    rag: config.rag.map((r) =>
                      r.collectionId === rag.collectionId ? { ...r, threshold: Number(e.target.value) } : r,
                    ),
                  })
                }
              />
            </label>
          </div>
        ))}
        {config.rag.length === 0 && <p className="text-xs text-gray-500">No knowledge collections attached.</p>}
      </Section>
    </div>
  )
}
