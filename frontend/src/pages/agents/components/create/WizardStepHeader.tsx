export function WizardStepHeader({
  title,
  subtitle,
}: {
  title: string
  subtitle?: string
}) {
  return (
    <div className="max-w-2xl">
      <h3 className="text-lg font-semibold text-gray-900 tracking-tight">{title}</h3>
      {subtitle ? <p className="text-sm text-gray-600 mt-1.5 leading-relaxed">{subtitle}</p> : null}
    </div>
  )
}
