import { useEffect, useState, type ComponentType } from 'react'
import { Link } from 'react-router-dom'
import { Bot, FileText, Mic, Plug, Sparkles, Users, Volume2 } from 'lucide-react'
import { useWalkthrough } from '../../context/WalkthroughContext'
import type { WalkthroughSectionId } from './walkthroughRegistry'

const sectionIcons: Record<WalkthroughSectionId, ComponentType<{ className?: string }>> = {
  integrations: Plug,
  voicebundles: Mic,
  agents: Bot,
  personas: Users,
  scenarios: FileText,
  evaluators: Mic,
  'voice-playground': Volume2,
  'prompt-optimization': Sparkles,
}

export default function WalkthroughRail() {
  const { activeDefinition, isCollapsed } = useWalkthrough()
  const [railTopPx, setRailTopPx] = useState(96)
  const [railMaxHeightPx, setRailMaxHeightPx] = useState(480)

  useEffect(() => {
    const updateRailMetrics = () => {
      const viewportHeight = window.innerHeight || 800
      // Keep walkthrough position consistent across pages and aligned with
      // top action rows (e.g. primary Create button).
      const top = 96
      const maxHeight = Math.max(viewportHeight - top - 24, 320)
      setRailTopPx(top)
      setRailMaxHeightPx(maxHeight)
    }

    updateRailMetrics()
    window.addEventListener('resize', updateRailMetrics)
    return () => window.removeEventListener('resize', updateRailMetrics)
  }, [])

  if (!activeDefinition || isCollapsed) {
    return null
  }

  const SectionIcon = sectionIcons[activeDefinition.id]

  return (
    <aside
      className="hidden lg:block pointer-events-none"
      aria-label="Section walkthrough"
    >
      <div
        className="fixed right-6 w-[340px] rounded-xl border border-gray-200/90 bg-white/95 shadow-sm flex flex-col min-h-0 overflow-hidden z-[10010] pointer-events-auto"
        style={{ top: `${railTopPx}px`, maxHeight: `${railMaxHeightPx}px` }}
      >
        <div className="flex items-center gap-2 border-b border-gray-200 p-3">
          <div className="flex items-center gap-2 min-w-0">
            <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-amber-500 text-white shrink-0 shadow-sm">
              <SectionIcon className="h-3.5 w-3.5" />
            </span>
            <h2 className="text-sm font-semibold text-gray-900 truncate">
              {activeDefinition.title}
            </h2>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          <p className="text-xs text-gray-600 mb-3">{activeDefinition.subtitle}</p>
          <ol className="space-y-3">
            {activeDefinition.steps.map((step, index) => (
              <li key={`${activeDefinition.id}-${step.title}`}>
                <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-3">
                  <div className="flex items-start gap-2">
                    <span className="mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full bg-primary-100 text-[11px] font-semibold text-primary-700">
                      {index + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold text-gray-900">{step.title}</p>
                      <p className="mt-1 text-xs text-gray-700">{step.description}</p>
                      {step.bullets && step.bullets.length > 0 && (
                        <ul className="mt-2 list-disc pl-4 text-xs text-gray-600 space-y-1">
                          {step.bullets.map((bullet) => (
                            <li key={bullet}>{bullet}</li>
                          ))}
                        </ul>
                      )}
                      {step.ctaLabel && step.ctaPath && (
                        <Link
                          to={step.ctaPath}
                          className="inline-flex items-center mt-2 text-xs font-medium text-primary-700 hover:text-primary-800"
                        >
                          {step.ctaLabel}
                        </Link>
                      )}
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </aside>
  )
}
