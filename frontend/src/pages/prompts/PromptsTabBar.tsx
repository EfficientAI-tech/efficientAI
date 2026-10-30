import { Link, useLocation } from 'react-router-dom'
import { ScrollText, Sparkles, Scale, type LucideIcon } from 'lucide-react'

type PromptsTab = {
  id: string
  label: string
  href: string
  icon: LucideIcon
}

const TABS: PromptsTab[] = [
  { id: 'partials', label: 'Partials', href: '/prompts/partials', icon: ScrollText },
  { id: 'optimization', label: 'Optimization', href: '/prompts/optimization', icon: Sparkles },
  { id: 'judge-alignment', label: 'Judge Alignment', href: '/prompts/judge-alignment', icon: Scale },
]

export default function PromptsTabBar() {
  const location = useLocation()

  return (
    <div className="border-b border-gray-200">
      <nav className="-mb-px flex gap-6 overflow-x-auto" aria-label="Prompts sections">
        {TABS.map((tab) => {
          const active =
            location.pathname === tab.href || location.pathname.startsWith(`${tab.href}/`)
          const Icon = tab.icon
          return (
            <Link
              key={tab.id}
              to={tab.href}
              className={`flex items-center gap-2 px-1 py-3 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
                active
                  ? 'border-primary-600 text-primary-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              <Icon className="h-4 w-4" />
              {tab.label}
            </Link>
          )
        })}
      </nav>
    </div>
  )
}
