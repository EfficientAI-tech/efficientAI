export const METRIC_SURFACES = [
  'agent',
  'chat_agent',
  'voice_playground',
  'blind_test',
] as const

export type MetricSurface = (typeof METRIC_SURFACES)[number]

export const ALL_SURFACES: MetricSurface[] = [...METRIC_SURFACES]

export const METRIC_SURFACE_LABELS: Record<MetricSurface, string> = {
  agent: 'Voice agent',
  chat_agent: 'Chat agent',
  voice_playground: 'Voice Playground',
  blind_test: 'Blind Test',
}

export function metricSurfaceLabel(surface: string): string {
  return METRIC_SURFACE_LABELS[surface as MetricSurface] ?? surface
}

export function metricListSurfaceForAgentMedium(medium: 'voice' | 'chat'): MetricSurface {
  return medium === 'chat' ? 'chat_agent' : 'agent'
}
