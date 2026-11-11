import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

type Coords = { top: number; left: number; placement: 'above' | 'below' }

type UsageMetricValueProps = {
  display: string
  exact: string
  className?: string
}

function placeTooltip(anchor: HTMLElement): Coords {
  const rect = anchor.getBoundingClientRect()
  const center = rect.left + rect.width / 2
  const left = Math.min(window.innerWidth - 12, Math.max(12, center))
  const placement = rect.top < 48 ? 'below' : 'above'
  return {
    top: placement === 'above' ? rect.top - 6 : rect.bottom + 6,
    left,
    placement,
  }
}

/** Compact metric with the exact value in a viewport tooltip. */
export default function UsageMetricValue({
  display,
  exact,
  className = '',
}: UsageMetricValueProps) {
  const anchorRef = useRef<HTMLSpanElement>(null)
  const tipRef = useRef<HTMLSpanElement>(null)
  const [coords, setCoords] = useState<Coords | null>(null)
  const [shift, setShift] = useState(0)
  const reveal = Boolean(exact) && exact !== display

  useLayoutEffect(() => {
    if (!coords || !tipRef.current) return
    const width = tipRef.current.offsetWidth
    const half = width / 2
    const overflowRight = coords.left + half - (window.innerWidth - 12)
    const overflowLeft = 12 - (coords.left - half)
    if (overflowRight > 0) setShift(-overflowRight)
    else if (overflowLeft > 0) setShift(overflowLeft)
    else setShift(0)
  }, [coords, exact])

  useEffect(() => {
    if (!coords || !anchorRef.current) return
    const update = () => {
      if (anchorRef.current) setCoords(placeTooltip(anchorRef.current))
    }
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)
    return () => {
      window.removeEventListener('resize', update)
      window.removeEventListener('scroll', update, true)
    }
  }, [coords])

  return (
    <span
      ref={anchorRef}
      className={`tabular-nums whitespace-nowrap ${reveal ? 'cursor-help' : ''} ${className}`}
      aria-label={reveal ? exact : undefined}
      onMouseEnter={() => {
        if (reveal && anchorRef.current) setCoords(placeTooltip(anchorRef.current))
      }}
      onMouseLeave={() => setCoords(null)}
      onFocus={() => {
        if (reveal && anchorRef.current) setCoords(placeTooltip(anchorRef.current))
      }}
      onBlur={() => setCoords(null)}
      tabIndex={reveal ? 0 : undefined}
    >
      {display}
      {coords && reveal && typeof document !== 'undefined'
        ? createPortal(
            <span
              ref={tipRef}
              role="tooltip"
              className="pointer-events-none whitespace-nowrap rounded-md bg-gray-900 px-2 py-1 text-xs font-medium text-white shadow-lg"
              style={{
                position: 'fixed',
                top: coords.top,
                left: coords.left,
                transform:
                  coords.placement === 'above'
                    ? `translate(calc(-50% + ${shift}px), -100%)`
                    : `translate(calc(-50% + ${shift}px), 0)`,
                zIndex: 80,
              }}
            >
              {exact}
            </span>,
            document.body,
          )
        : null}
    </span>
  )
}
