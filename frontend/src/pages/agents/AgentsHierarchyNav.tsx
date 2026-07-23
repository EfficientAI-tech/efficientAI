import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'

export type AgentsHierarchyCrumb = { label: string; to?: string }

export default function AgentsHierarchyNav({
  crumbs,
  className = 'mb-4',
}: {
  crumbs: AgentsHierarchyCrumb[]
  className?: string
}) {
  return (
    <nav
      className={`flex items-center flex-wrap gap-1 text-sm text-gray-500 ${className}`}
      aria-label="Breadcrumb"
    >
      {crumbs.map((crumb, index) => (
        <span key={`${crumb.label}-${index}`} className="flex items-center gap-1">
          {index > 0 && <ChevronRight className="w-4 h-4 text-gray-300" />}
          {crumb.to ? (
            <Link to={crumb.to} className="text-primary-600 hover:text-primary-800 font-medium">
              {crumb.label}
            </Link>
          ) : (
            <span className="text-gray-900 font-medium">{crumb.label}</span>
          )}
        </span>
      ))}
    </nav>
  )
}
