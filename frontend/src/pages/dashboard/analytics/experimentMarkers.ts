export function experimentMarkers(
  runs: Array<{ created_at: string; agent_id: string }>,
  agentId?: string | null,
): Array<{ date: string; label: string; kind: 'experiment' | 'break' }> {
  return runs
    .filter((run) => !agentId || run.agent_id === agentId)
    .map((run) => ({
      date: run.created_at.slice(0, 10),
      label: 'GEPA',
      kind: 'experiment' as const,
    }))
}
