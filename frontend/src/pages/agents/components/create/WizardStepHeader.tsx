export function WizardStepHeader({
  title,
  subtitle,
  prominence = 'default',
}: {
  title: string
  subtitle?: string
  /** Larger title for compact create-agent entry screens. */
  prominence?: 'default' | 'entry'
}) {
  const titleClass =
    prominence === 'entry'
      ? 'text-base font-semibold text-gray-900 tracking-tight'
      : 'text-lg font-semibold text-gray-900 tracking-tight'

  return (
    <div className="max-w-2xl">
      <h3 className={titleClass}>{title}</h3>
      {subtitle ? (
        <p
          className={`leading-snug ${
            prominence === 'entry'
              ? 'text-xs text-gray-500 mt-1'
              : 'text-sm text-gray-600 mt-1.5 leading-relaxed'
          }`}
        >
          {subtitle}
        </p>
      ) : null}
    </div>
  )
}
