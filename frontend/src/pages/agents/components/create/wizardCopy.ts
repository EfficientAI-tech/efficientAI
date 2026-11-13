/** Shared create-wizard label for Vapi / Retell / ElevenLabs / Smallest (voice or chat). */
export const WIZARD_EXISTING_PLATFORM_LABEL = 'Existing platform'

/** Grid columns sized to the number of visible choice cards (avoids empty columns when a licensed option is hidden). */
export function wizardOptionGridClass(optionCount: number, compact: boolean): string {
  const gap = compact ? 'gap-3.5 mt-4' : 'gap-4 mt-6'
  const smCols =
    optionCount >= 3 ? 'sm:grid-cols-3' : optionCount === 2 ? 'sm:grid-cols-2' : ''
  return `grid w-full grid-cols-1 ${gap} ${smCols}`.trim()
}
