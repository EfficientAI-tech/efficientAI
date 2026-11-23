import { useMemo } from 'react'
import { CornerDownRight } from 'lucide-react'
import type { RedTeamAttack } from '../../types/redTeam'
import { AttackOutcomeChip } from './redTeamUi'
import { attackCategoryLabel, humanizeId } from './redTeamFormat'

interface Props {
  attacks: RedTeamAttack[]
  selectedAttackId: string | null
  onSelect: (attack: RedTeamAttack) => void
  familyNames?: Map<string, string>
}

const bySequence = (a: RedTeamAttack, b: RedTeamAttack) => a.level - b.level || a.sequence - b.sequence

function AttackNode({
  attack,
  depth,
  selected,
  onSelect,
  familyName,
}: {
  attack: RedTeamAttack
  depth: number
  selected: boolean
  onSelect: () => void
  familyName?: string
}) {
  const category = attackCategoryLabel(attack)
  return (
    <button
      type="button"
      onClick={onSelect}
      style={{ marginLeft: depth * 24, width: `calc(100% - ${depth * 24}px)` }}
      className={`flex items-center gap-3 rounded-lg border px-3 py-2 text-left transition-colors ${
        selected ? 'border-primary-500 bg-primary-50' : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
      }`}
    >
      {depth > 0 ? <CornerDownRight className="h-3.5 w-3.5 shrink-0 text-gray-400" /> : null}
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-gray-900">
          {attack.kind === 'recon' ? `Recon probe ${attack.sequence}` : attack.technique_name || humanizeId(attack.technique_id)}
        </div>
        <div className="truncate text-[11px] text-gray-500">
          {attack.kind === 'recon'
            ? attack.goal || 'Maps what the agent holds and guards'
            : [familyName ?? humanizeId(attack.family), category, `L${attack.level}`].filter(Boolean).join(' · ')}
        </div>
      </div>
      {attack.score != null ? (
        <span className="shrink-0 text-xs tabular-nums text-gray-600" title="Judge score (0–10)">
          {attack.score.toFixed(1)}
        </span>
      ) : null}
      <AttackOutcomeChip attack={attack} />
    </button>
  )
}

/** Recon probes, then the attack tree: roots grouped by level, refinements indented under their parent. */
export default function RedTeamSwarmTree({ attacks, selectedAttackId, onSelect, familyNames }: Props) {
  const { recon, rootsByLevel, children } = useMemo(() => {
    const recon = attacks.filter((a) => a.kind === 'recon').sort(bySequence)
    const offensive = attacks.filter((a) => a.kind !== 'recon')
    const ids = new Set(offensive.map((a) => a.id))
    const children = new Map<string, RedTeamAttack[]>()
    const rootsByLevel = new Map<number, RedTeamAttack[]>()
    for (const a of offensive) {
      if (a.parent_attack_id && ids.has(a.parent_attack_id)) {
        children.set(a.parent_attack_id, [...(children.get(a.parent_attack_id) ?? []), a])
      } else {
        rootsByLevel.set(a.level, [...(rootsByLevel.get(a.level) ?? []), a])
      }
    }
    for (const list of children.values()) list.sort(bySequence)
    for (const list of rootsByLevel.values()) list.sort(bySequence)
    return { recon, rootsByLevel: [...rootsByLevel.entries()].sort(([a], [b]) => a - b), children }
  }, [attacks])

  if (attacks.length === 0) {
    return <p className="text-sm text-gray-500">No conversations yet. Recon starts as soon as the run is picked up.</p>
  }

  const renderSubtree = (attack: RedTeamAttack, depth: number, seen: Set<string>): JSX.Element[] => {
    if (seen.has(attack.id)) return []
    seen.add(attack.id)
    return [
      <AttackNode
        key={attack.id}
        attack={attack}
        depth={depth}
        selected={attack.id === selectedAttackId}
        onSelect={() => onSelect(attack)}
        familyName={attack.family ? familyNames?.get(attack.family) : undefined}
      />,
      ...(children.get(attack.id) ?? []).flatMap((child) => renderSubtree(child, depth + 1, seen)),
    ]
  }
  const seen = new Set<string>()

  return (
    <div className="space-y-5">
      {recon.length ? (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Recon <span className="font-normal normal-case">({recon.length})</span>
          </h3>
          <div className="space-y-1.5">
            {recon.map((a) => (
              <AttackNode
                key={a.id}
                attack={a}
                depth={0}
                selected={a.id === selectedAttackId}
                onSelect={() => onSelect(a)}
              />
            ))}
          </div>
        </section>
      ) : null}
      {rootsByLevel.map(([level, roots]) => (
        <section key={level}>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Level {level} <span className="font-normal normal-case">({roots.length} starting attacks)</span>
          </h3>
          <div className="space-y-1.5">{roots.flatMap((root) => renderSubtree(root, 0, seen))}</div>
        </section>
      ))}
    </div>
  )
}
