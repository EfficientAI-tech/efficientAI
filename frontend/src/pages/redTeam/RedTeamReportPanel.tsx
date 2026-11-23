import { Loader2, ScanSearch } from 'lucide-react'
import type { RedTeamAgentProfile, RedTeamReportCategory, RedTeamRun } from '../../types/redTeam'
import { CategoryStatusChip, VerdictBadge } from './redTeamUi'
import { isRedTeamRunActive } from './redTeamFormat'

function StatTile({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-4 py-3">
      <div className="text-xs font-medium text-gray-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${tone ?? 'text-gray-900'}`}>{value}</div>
      {hint ? <div className="mt-0.5 text-xs text-gray-500">{hint}</div> : null}
    </div>
  )
}

function ProfileList({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null
  return (
    <div>
      <dt className="text-xs font-medium text-gray-500">{title}</dt>
      <dd className="mt-1 flex flex-wrap gap-1">
        {items.map((item) => (
          <span key={item} className="rounded-md bg-gray-100 px-2 py-0.5 text-xs text-gray-700">
            {item}
          </span>
        ))}
      </dd>
    </div>
  )
}

export function AgentProfileCard({ profile }: { profile: RedTeamAgentProfile | null }) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold text-gray-900">
        <ScanSearch className="h-4 w-4 text-gray-500" /> Agent profile
      </h2>
      <p className="mb-3 text-xs text-gray-500">What the recon conversations learned about the agent before attacking.</p>
      {profile ? (
        <dl className="space-y-3">
          {profile.summary ? <p className="text-sm text-gray-700">{profile.summary}</p> : null}
          <ProfileList title="Data it holds" items={profile.data_held} />
          <ProfileList title="Gated actions" items={profile.gated_actions} />
          <ProfileList title="Verification steps" items={profile.verification_steps} />
          <ProfileList title="Refused topics" items={profile.refused_topics} />
          <ProfileList title="Tools" items={profile.tools} />
        </dl>
      ) : (
        <p className="text-sm text-gray-500">Available once recon finishes.</p>
      )}
    </section>
  )
}

function CategoryList({ title, tone, categories, empty }: {
  title: string
  tone: string
  categories: { id: string; name: string; detail?: string }[]
  empty: string
}) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4">
      <h3 className={`mb-2 text-sm font-semibold ${tone}`}>
        {title} <span className="font-normal text-gray-500">({categories.length})</span>
      </h3>
      {categories.length ? (
        <ul className="space-y-1.5 text-sm">
          {categories.map((c) => (
            <li key={c.id} className="flex items-baseline justify-between gap-3">
              <span className="text-gray-900">
                <span className="mr-1.5 font-mono text-xs text-gray-500">{c.id.replace(/^harm:/, '')}</span>
                {c.name}
              </span>
              {c.detail ? <span className="shrink-0 text-xs tabular-nums text-gray-500">{c.detail}</span> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-gray-500">{empty}</p>
      )}
    </section>
  )
}

function CategoryGrid({ title, categories }: { title: string; categories: RedTeamReportCategory[] }) {
  if (!categories.length) return null
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4">
      <h2 className="mb-3 text-sm font-semibold text-gray-900">{title}</h2>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {categories.map((c) => (
          <div key={c.id} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                {c.kind === 'owasp' ? <div className="font-mono text-[11px] text-gray-500">{c.id}</div> : null}
                <div className="text-sm font-medium text-gray-900">{c.name}</div>
              </div>
              <CategoryStatusChip status={c.status} />
            </div>
            <div className="mt-1 text-[11px] tabular-nums text-gray-500">
              {c.attacks
                ? `${c.attacks} attacks · ${c.breached} breached · ${c.conceded} conceded · ${c.held} held`
                : 'No attacks'}
              {c.max_success_score != null ? ` · max success ${Math.round(c.max_success_score)}` : ''}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

export default function RedTeamReportPanel({ run }: { run: RedTeamRun }) {
  const report = run.report
  if (!report) {
    const active = isRedTeamRunActive(run.status)
    return (
      <div className="space-y-6">
        <div className="flex flex-col items-center rounded-lg border border-dashed border-gray-300 px-6 py-10 text-center">
          {active ? <Loader2 className="mb-2 h-8 w-8 animate-spin text-gray-400" /> : null}
          <p className="text-sm font-medium text-gray-900">{active ? 'Report in progress' : 'No report'}</p>
          <p className="mt-1 text-sm text-gray-500">
            {active
              ? 'The report is built once every attack has been judged. Watch progress in the Swarm tab.'
              : 'This run ended before a report could be generated.'}
          </p>
        </div>
        <AgentProfileCard profile={run.agent_profile} />
      </div>
    )
  }

  const categoryName = new Map(report.categories.map((c) => [c.id, c.name]))
  const breached = report.categories.filter((c) => c.breached > 0 || c.status === 'FAIL')
  const conceded = report.categories.filter((c) => !breached.includes(c) && (c.conceded > 0 || c.status === 'PARTIAL'))
  const notAssessed = report.not_assessed.map((id) => ({ id, name: categoryName.get(id) ?? id.replace(/^harm:/, '') }))
  const owasp = report.categories.filter((c) => c.kind === 'owasp')
  const harm = report.categories.filter((c) => c.kind === 'harm')
  const t = report.totals

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-gray-200 bg-white px-4 py-3">
        <VerdictBadge verdict={report.verdict} size="lg" />
        <span className="text-sm text-gray-600">
          {report.passed ? 'The agent passed this red team.' : 'The agent did not pass this red team.'}
          {report.content_harm_failed ? ' It produced harmful content in at least one category.' : ''}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Attacks" value={String(t.attacks)} hint={`plus ${t.recon} recon`} />
        <StatTile label="Breached" value={String(t.breached)} tone={t.breached ? 'text-red-700' : undefined} />
        <StatTile label="Conceded ground" value={String(t.conceded)} tone={t.conceded ? 'text-amber-700' : undefined} />
        <StatTile label="Held" value={String(t.held)} tone={t.held ? 'text-green-700' : undefined} />
        <StatTile label="Errors" value={String(t.errors)} hint="not judged" />
        <StatTile
          label="Breach rate"
          value={t.attacks ? `${Math.round((t.breached / t.attacks) * 100)}%` : '—'}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <CategoryList
          title="Breached"
          tone="text-red-700"
          empty="No category was breached."
          categories={breached.map((c) => ({ id: c.id, name: c.name, detail: `${c.breached}/${c.attacks}` }))}
        />
        <CategoryList
          title="Conceded ground"
          tone="text-amber-700"
          empty="The agent never partially gave way."
          categories={conceded.map((c) => ({ id: c.id, name: c.name, detail: `${c.conceded}/${c.attacks}` }))}
        />
        <CategoryList title="Not assessed" tone="text-gray-700" empty="Every category was tested." categories={notAssessed} />
      </div>

      <CategoryGrid title="OWASP LLM Top 10" categories={owasp} />
      <CategoryGrid title="Content harm" categories={harm} />

      {report.families.length ? (
        <section className="rounded-lg border border-gray-200 bg-white">
          <h2 className="border-b border-gray-200 px-4 py-3 text-sm font-semibold text-gray-900">Attack families</h2>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-3 py-2">Family</th>
                  <th className="px-3 py-2 text-right">Quota</th>
                  <th className="px-3 py-2 text-right">Attempts</th>
                  <th className="px-3 py-2 text-right">Breached</th>
                  <th className="px-3 py-2 text-right">Conceded</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {report.families.map((f) => (
                  <tr key={f.id}>
                    <td className="px-3 py-2 text-gray-900">{f.name}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-gray-700">{f.quota}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-gray-700">{f.attempts}</td>
                    <td className={`px-3 py-2 text-right tabular-nums ${f.breached ? 'font-semibold text-red-700' : 'text-gray-700'}`}>
                      {f.breached}
                    </td>
                    <td className={`px-3 py-2 text-right tabular-nums ${f.conceded ? 'text-amber-700' : 'text-gray-700'}`}>
                      {f.conceded}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <AgentProfileCard profile={run.agent_profile} />
    </div>
  )
}
