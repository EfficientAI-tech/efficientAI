import { Link } from 'react-router-dom'
import { MapPinned } from 'lucide-react'
import { useWalkthrough } from '../../context/WalkthroughContext'

export default function WalkthroughRail() {
  const { activeDefinition, isCollapsed, toggleCollapsed } = useWalkthrough()

  if (!activeDefinition) {
    return null
  }

  return (
    <aside
      className={`hidden lg:flex shrink-0 transition-[width] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none ${
        isCollapsed ? 'w-14' : 'w-[340px]'
      }`}
      aria-label="Section walkthrough"
    >
      {isCollapsed ? (
        <div className="w-full pt-2 flex justify-center">
          <button
            type="button"
            onClick={toggleCollapsed}
            className="group inline-flex h-10 w-10 items-center justify-center rounded-xl border border-gray-200/90 bg-white text-primary-700 shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-primary-300 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
            aria-label="Expand walkthrough"
          >
            <MapPinned className="h-4 w-4 transition-transform duration-200 group-hover:scale-105" />
          </button>
        </div>
      ) : (
        <div className="h-full w-full rounded-xl border border-gray-200/90 bg-white/95 shadow-sm backdrop-blur-sm flex flex-col min-h-0 overflow-hidden">
          <div className="flex items-center justify-between gap-2 border-b border-gray-200 p-3">
            <div className="flex items-center gap-2 min-w-0">
              <MapPinned className="h-4 w-4 text-primary-600 shrink-0" />
              <h2 className="text-sm font-semibold text-gray-900 truncate">
                {activeDefinition.title}
              </h2>
            </div>
            <button
              type="button"
              onClick={toggleCollapsed}
              className="rounded-md border border-gray-200 bg-white p-1 text-gray-500 transition-colors hover:text-primary-700 hover:bg-gray-50"
              aria-label="Collapse walkthrough"
            >
              <MapPinned className="h-4 w-4" />
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
