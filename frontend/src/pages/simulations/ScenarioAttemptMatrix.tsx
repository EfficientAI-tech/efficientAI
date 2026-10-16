import { useMemo } from 'react'
import { CheckCircle2, XCircle } from 'lucide-react'
import type { SimulationTrial } from '../../types/api'
import { formatScore, rewardCellStyle } from './simulationFormat'

interface Props {
  trials: SimulationTrial[]
  nAttempts: number
  onSelect: (trial: SimulationTrial) => void
  selectedTrialId?: string | null
}

interface Row {
  key: string
  scenarioName: string
  personaName: string
  byAttempt: Map<number, SimulationTrial>
  passed: number
  finished: number
}

/** Rows = scenario × persona, columns = attempts; cell shade = reward (sequential blue). */
export default function ScenarioAttemptMatrix({ trials, nAttempts, onSelect, selectedTrialId }: Props) {
  const rows = useMemo(() => {
    const map = new Map<string, Row>()
    for (const trial of trials) {
      const key = `${trial.scenario_id}:${trial.persona_id}`
      const row =
        map.get(key) ??
        ({
          key,
          scenarioName: trial.scenario_name || 'Scenario',
          personaName: trial.persona_name || 'Persona',
          byAttempt: new Map(),
          passed: 0,
          finished: 0,
        } as Row)
      row.byAttempt.set(trial.attempt_index ?? row.byAttempt.size + 1, trial)
      if (trial.passed !== null && trial.passed !== undefined) row.finished += 1
      if (trial.passed) row.passed += 1
      map.set(key, row)
    }
    // Weakest rows first so failures are on top.
    return [...map.values()].sort((a, b) => a.passed / Math.max(1, a.finished) - b.passed / Math.max(1, b.finished))
  }, [trials])

  const attempts = Array.from({ length: nAttempts }, (_, i) => i + 1)

  if (rows.length === 0) {
    return <p className="text-sm text-gray-500">Trials will appear here as soon as the first conversation starts.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="text-left text-xs font-medium text-gray-500">
            <th className="py-2 pr-4">Scenario · Persona</th>
            {attempts.map((a) => (
              <th key={a} className="px-1 py-2 text-center">
                #{a}
              </th>
            ))}
            <th className="py-2 pl-4 text-right">Passed</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-t border-gray-100">
              <td className="max-w-xs py-1.5 pr-4">
                <span className="block truncate text-gray-900" title={row.scenarioName}>
                  {row.scenarioName}
                </span>
                <span className="block truncate text-xs text-gray-500">{row.personaName}</span>
              </td>
              {attempts.map((a) => {
                const trial = row.byAttempt.get(a)
                if (!trial) {
                  return (
                    <td key={a} className="px-1 py-1.5">
                      <div className="mx-auto h-9 w-16 rounded-md border border-dashed border-gray-200" />
                    </td>
                  )
                }
                const style = rewardCellStyle(trial.reward)
                const label =
                  trial.status === 'failed'
                    ? 'Error'
                    : trial.reward === null || trial.reward === undefined
                      ? '…'
                      : formatScore(trial.reward)
                return (
                  <td key={a} className="px-1 py-1.5">
                    <button
                      type="button"
                      onClick={() => onSelect(trial)}
                      title={`${row.scenarioName} · attempt ${a}\nScore ${formatScore(trial.reward)} · ${
                        trial.status === 'failed' ? 'error' : trial.passed ? 'pass' : trial.passed === false ? 'fail' : 'running'
                      } · ${trial.turns} turns`}
                      className={`mx-auto flex h-9 w-16 items-center justify-center gap-1 rounded-md text-xs font-medium tabular-nums ring-offset-1 transition hover:ring-2 hover:ring-gray-400 ${
                        selectedTrialId === trial.id ? 'ring-2 ring-gray-900' : ''
                      }`}
                      style={{ background: style.background, color: style.color }}
                    >
                      {trial.status === 'failed' || trial.passed === false ? (
                        <XCircle className="h-3 w-3" aria-label="failed" />
                      ) : trial.passed ? (
                        <CheckCircle2 className="h-3 w-3" aria-label="passed" />
                      ) : null}
                      {label}
                    </button>
                  </td>
                )
              })}
              <td className="py-1.5 pl-4 text-right tabular-nums text-gray-700">
                {row.passed}/{row.byAttempt.size}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
        <span>Score</span>
        <span>0</span>
        {[0.05, 0.25, 0.4, 0.6, 0.75, 0.95].map((v) => (
          <span key={v} className="h-3 w-6 rounded-sm" style={{ background: rewardCellStyle(v).background }} />
        ))}
        <span>1</span>
        <span className="ml-3 inline-flex items-center gap-1">
          <CheckCircle2 className="h-3 w-3" /> pass
        </span>
        <span className="inline-flex items-center gap-1">
          <XCircle className="h-3 w-3" /> fail / error
        </span>
      </div>
    </div>
  )
}
