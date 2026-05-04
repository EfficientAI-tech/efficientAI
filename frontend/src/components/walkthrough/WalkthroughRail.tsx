import { useCallback, useEffect, useRef, useState, type ComponentType } from 'react'
import { Link } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Bot, FileText, Mic, Plug, Sparkles, Users, Volume2, X } from 'lucide-react'
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
  const { activeDefinition, isCollapsed, setCollapsed } = useWalkthrough()
  const panelRef = useRef<HTMLDivElement | null>(null)
  const dragOffsetRef = useRef({ x: 0, y: 0 })
  const isDraggingRef = useRef(false)

  const [isDesktop, setIsDesktop] = useState<boolean>(() => {
    if (typeof window === 'undefined') return true
    return window.innerWidth >= 1024
  })
  const [viewport, setViewport] = useState(() => ({
    width: typeof window === 'undefined' ? 1440 : window.innerWidth,
    height: typeof window === 'undefined' ? 900 : window.innerHeight,
  }))
  const [position, setPosition] = useState({ x: 0, y: 0 })
  const [hasPosition, setHasPosition] = useState(false)

  const PANEL_WIDTH = 340
  const DESKTOP_MIN_HEIGHT = 320
  const VIEWPORT_MARGIN = 12
  const TOP_BAR_HEIGHT = 64
  const DESKTOP_SIDEBAR_WIDTH = 256

  const getBounds = useCallback(() => {
    const panelRect = panelRef.current?.getBoundingClientRect()
    const panelWidth = panelRect?.width ?? PANEL_WIDTH
    const panelHeight = panelRect?.height ?? 480

    const minX = DESKTOP_SIDEBAR_WIDTH + VIEWPORT_MARGIN
    const minY = TOP_BAR_HEIGHT + VIEWPORT_MARGIN
    const maxX = Math.max(minX, viewport.width - panelWidth - VIEWPORT_MARGIN)
    const maxY = Math.max(minY, viewport.height - panelHeight - VIEWPORT_MARGIN)

    return { minX, minY, maxX, maxY }
  }, [viewport.width, viewport.height])

  const clampPosition = useCallback((x: number, y: number) => {
    const bounds = getBounds()
    return {
      x: Math.min(Math.max(x, bounds.minX), bounds.maxX),
      y: Math.min(Math.max(y, bounds.minY), bounds.maxY),
    }
  }, [getBounds])

  useEffect(() => {
    const syncViewportMode = () => {
      setViewport({ width: window.innerWidth, height: window.innerHeight })
      setIsDesktop(window.innerWidth >= 1024)
    }
    syncViewportMode()
    window.addEventListener('resize', syncViewportMode)
    return () => window.removeEventListener('resize', syncViewportMode)
  }, [])

  useEffect(() => {
    if (!activeDefinition || isCollapsed || !isDesktop) {
      setHasPosition(false)
      return
    }

    if (!hasPosition) {
      const defaultX = viewport.width - PANEL_WIDTH - VIEWPORT_MARGIN
      const defaultY = TOP_BAR_HEIGHT + VIEWPORT_MARGIN
      setPosition(clampPosition(defaultX, defaultY))
      setHasPosition(true)
      return
    }

    setPosition((prev) => clampPosition(prev.x, prev.y))
  }, [activeDefinition, isCollapsed, isDesktop, hasPosition, viewport.width, viewport.height, clampPosition])

  if (!activeDefinition) {
    return null
  }

  const SectionIcon = sectionIcons[activeDefinition.id]
  const desktopPanelHeight = Math.max(viewport.height - TOP_BAR_HEIGHT - VIEWPORT_MARGIN * 2, DESKTOP_MIN_HEIGHT)

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!isDesktop) return
    const panelRect = panelRef.current?.getBoundingClientRect()
    if (!panelRect) return

    isDraggingRef.current = true
    dragOffsetRef.current = {
      x: event.clientX - panelRect.left,
      y: event.clientY - panelRect.top,
    }
    ;(event.currentTarget as HTMLDivElement).setPointerCapture(event.pointerId)
  }

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!isDesktop || !isDraggingRef.current) return
    const rawX = event.clientX - dragOffsetRef.current.x
    const rawY = event.clientY - dragOffsetRef.current.y
    setPosition(clampPosition(rawX, rawY))
  }

  const handlePointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!isDesktop) return
    if (isDraggingRef.current) {
      isDraggingRef.current = false
      if ((event.currentTarget as HTMLDivElement).hasPointerCapture(event.pointerId)) {
        ;(event.currentTarget as HTMLDivElement).releasePointerCapture(event.pointerId)
      }
    }
  }

  const panelStyle = isDesktop
    ? {
        left: `${position.x}px`,
        top: `${position.y}px`,
        width: `${PANEL_WIDTH}px`,
        maxHeight: `${desktopPanelHeight}px`,
      }
    : {
        left: '50%',
        top: `${TOP_BAR_HEIGHT + VIEWPORT_MARGIN}px`,
        transform: 'translateX(-50%)',
        width: 'min(92vw, 360px)',
        maxHeight: `calc(100vh - ${TOP_BAR_HEIGHT + VIEWPORT_MARGIN * 2}px)`,
      }

  return (
    <aside className="pointer-events-none" aria-label="Section walkthrough">
      <AnimatePresence>
        {!isCollapsed && (
          <motion.div
            key={activeDefinition.id}
            ref={panelRef}
            className="fixed rounded-xl border border-gray-200/90 bg-white/95 shadow-lg flex flex-col min-h-0 overflow-hidden z-[10030] pointer-events-auto"
            style={panelStyle}
            initial={{ opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
          >
            <div className="flex items-center justify-between gap-2 border-b border-gray-200 p-3">
              <div
                className={`flex items-center gap-2 min-w-0 ${isDesktop ? 'cursor-move' : ''}`}
                onPointerDown={handlePointerDown}
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerUp}
                onPointerCancel={handlePointerUp}
              >
                <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-amber-500 text-white shrink-0 shadow-sm">
                  <SectionIcon className="h-3.5 w-3.5" />
                </span>
                <h2 className="text-sm font-semibold text-gray-900 truncate">
                  {activeDefinition.title}
                </h2>
              </div>
              <button
                type="button"
                className="inline-flex h-7 w-7 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                onClick={() => setCollapsed(true)}
                aria-label="Close how to guide"
                title="Close how to guide"
              >
                <X className="h-4 w-4" />
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
          </motion.div>
        )}
      </AnimatePresence>
    </aside>
  )
}
