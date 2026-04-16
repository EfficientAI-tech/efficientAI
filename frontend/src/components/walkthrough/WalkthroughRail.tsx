import type { ComponentType } from 'react'
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
  const { activeDefinition, isCollapsed, toggleCollapsed } = useWalkthrough()

  if (!activeDefinition) {
    return null
  }

  const SectionIcon = sectionIcons[activeDefinition.id]

  return (
    <aside
      className={`hidden lg:flex shrink-0 relative z-[10050] transition-[width] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none ${
        isCollapsed ? 'w-14' : 'w-[340px]'
      }`}
      aria-label="Section walkthrough"
    >
      {isCollapsed ? (
        <div className="w-full pt-2 flex justify-center">
          <button
            type="button"
            onClick={toggleCollapsed}
            className="group inline-flex h-10 w-10 items-center justify-center rounded-xl border border-amber-500 bg-amber-500 text-white shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:bg-amber-600 hover:border-amber-600 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-300"
            aria-label="Expand walkthrough"
          >
            <SectionIcon className="h-4 w-4 transition-transform duration-200 group-hover:scale-105" />
          </button>
        </div>
      ) : (
        <div className="h-full w-full rounded-xl border border-gray-200/90 bg-white/95 shadow-sm flex flex-col min-h-0 overflow-hidden">
          <div className="flex items-center justify-between gap-2 border-b border-gray-200 p-3">
            <div className="flex items-center gap-2 min-w-0">
              <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-amber-500 text-white shrink-0 shadow-sm">
                <SectionIcon className="h-3.5 w-3.5" />
              </span>
              <h2 className="text-sm font-semibold text-gray-900 truncate">
                {activeDefinition.title}
              </h2>
            </div>
            <button
              type="button"
              onClick={toggleCollapsed}
              className="rounded-md border border-amber-500 bg-amber-500 p-1 text-white transition-colors hover:bg-amber-600 hover:border-amber-600"
              aria-label="Collapse walkthrough"
            >
              <SectionIcon className="h-4 w-4" />
            </button>
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
      )}
    </aside>
  )
}
