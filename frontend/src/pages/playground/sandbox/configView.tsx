import Button from '../../../components/Button'
import type { AgentConfig, Session } from '../../../lib/sandbox'

function AgentSnapshot({ title, config, focus }: { title: string; config: AgentConfig; focus?: string }) {
  return (
    <section className="rounded-lg border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
      <dl className="mt-2 space-y-1 text-sm text-gray-700">
        <div>
          <dt className="text-xs text-gray-500">Name</dt>
          <dd>{config.name}</dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500">Model</dt>
          <dd>
            {config.llm.provider} / {config.llm.model}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500">Framework</dt>
          <dd>{config.framework}</dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500">Harness</dt>
          <dd>{config.harness?.name ?? '—'}</dd>
        </div>
      </dl>
      <p className="mt-3 whitespace-pre-wrap rounded bg-gray-50 p-2 text-xs text-gray-800">{config.prompt || '—'}</p>
      <ul className="mt-3 space-y-1 text-xs">
        {config.tools.map((tool) => (
          <li
            key={tool.id}
            id={`config-tools-${tool.id}`}
            className={focus === `tools:${tool.id}` ? 'rounded bg-amber-50 p-1' : ''}
          >
            Tool · {tool.name} · {tool.access} · {tool.kind}
          </li>
        ))}
        {config.skills.map((skill) => (
          <li
            key={skill.id}
            id={`config-skills-${skill.id}`}
            className={focus === `skills:${skill.id}` ? 'rounded bg-amber-50 p-1' : ''}
          >
            Skill · {skill.name}
          </li>
        ))}
        {config.rag.map((rag) => (
          <li
            key={rag.collectionId}
            id={`config-rag-${rag.collectionId}`}
            className={focus === `rag:${rag.collectionId}` ? 'rounded bg-amber-50 p-1' : ''}
          >
            RAG · {rag.name}
          </li>
        ))}
      </ul>
    </section>
  )
}

export function ConfigChangeHistory({ session }: { session: Session }) {
  if (!session.configHistory?.length) return null
  return (
    <section className="mt-4">
      <h3 className="text-sm font-semibold text-gray-900">Config changes</h3>
      <ul className="mt-2 space-y-1 text-xs text-gray-600">
        {session.configHistory.map((item) => (
          <li key={item.ts}>
            {new Date(item.ts).toLocaleString()} — {item.summary}
          </li>
        ))}
      </ul>
    </section>
  )
}

export function ConfigSnapshotView({
  session,
  onDuplicate,
  focus,
}: {
  session: Session
  onDuplicate?: () => void
  focus?: string
}) {
  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm text-gray-600">
          Snapshot of exactly what ran. Later edits to the source agent do not change this session.
        </p>
        {onDuplicate && (
          <Button size="sm" variant="outline" onClick={onDuplicate}>
            Duplicate as new run
          </Button>
        )}
      </div>
      <div className="rounded-lg border border-gray-200 p-3 text-sm">
        <p className="font-medium">{session.environment.name}</p>
        <p className="text-xs text-gray-500">{session.environment.domain}</p>
        <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-xs text-gray-700">
          {session.environment.policy}
        </pre>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <AgentSnapshot title="Agent A (under test)" config={session.agentA} focus={focus} />
        {session.agentB && <AgentSnapshot title="Agent B (eval / user)" config={session.agentB} focus={focus} />}
      </div>
      <ConfigChangeHistory session={session} />
    </div>
  )
}
