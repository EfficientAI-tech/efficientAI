import type { ReactNode } from 'react'
import DrilldownBreadcrumb from './DrilldownBreadcrumb'
import { SECTION_LABELS, type DashboardSection } from './dashboardSection'

export default function SectionShell({
  section,
  current,
  onBack,
  children,
}: {
  section: DashboardSection
  current: string
  onBack: () => void
  children: ReactNode
}) {
  return (
    <div className="space-y-5">
      <DrilldownBreadcrumb
        items={[
          { label: SECTION_LABELS.overview, onClick: onBack },
          { label: current || SECTION_LABELS[section] },
        ]}
      />
      {children}
    </div>
  )
}
