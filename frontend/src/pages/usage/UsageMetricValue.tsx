import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

type UsageMetricValueProps = {
  display: string
  exact: string
  className?: string
}

type Placement = 'above' | 'below'

let activeId: string | null = null
const activeListeners = new Set<(id: string | null) => void>()
let pointer = { x: -1, y: -1 }

function setActive(id: string | null) {
  if (activeId === id) return
  activeId = id
  activeListeners.forEach((listener) => listener(id))
}

function placeTooltip(anchor: HTMLElement, tip: HTMLElement) {
  const rect = anchor.getBoundingClientRect()
  const placement: Placement = rect.top < 48 ? 'below' : 'above'
  const center = rect.left + rect.width / 2
  const left = Math.min(window.innerWidth - 12, Math.max(12, center))
  const top = placement === 'above' ? rect.top - 6 : rect.bottom + 6
  tip.style.top = `${top}px`
  tip.style.left = `${left}px`
  const width = tip.offsetWidth
  const half = width / 2
  const overflowRight = left + half - (window.innerWidth - 12)
  const overflowLeft = 12 - (left - half)
  const shift = overflowRight > 0 ? -overflowRight : overflowLeft > 0 ? overflowLeft : 0
  tip.style.transform =
    placement === 'above'
      ? `translate(calc(-50% + ${shift}px), -100%)`
      : `translate(calc(-50% + ${shift}px), 0)`
  tip.style.visibility = 'visible'
}

function pointerHits(anchor: HTMLElement) {
  if (pointer.x < 0 || pointer.y < 0) return false
  const hit = document.elementFromPoint(pointer.x, pointer.y)
  return !!hit && (hit === anchor || anchor.contains(hit))
}

/** True when the number is inside the viewport and not clipped by a scroll box. */
function anchorVisible(anchor: HTMLElement) {
  const rect = anchor.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) return false
  if (rect.bottom <= 0 || rect.top >= window.innerHeight) return false
  if (rect.right <= 0 || rect.left >= window.innerWidth) return false

  let parent = anchor.parentElement
  while (parent && parent !== document.documentElement) {
    const style = getComputedStyle(parent)
    const overflow = `${style.overflow}${style.overflowX}${style.overflowY}`
    if (/(auto|scroll|hidden|clip)/.test(overflow)) {
      const bounds = parent.getBoundingClientRect()
      const clipped =
        rect.bottom <= bounds.top + 1 ||
        rect.top >= bounds.bottom - 1 ||
        rect.right <= bounds.left + 1 ||
        rect.left >= bounds.right - 1
      if (clipped) return false
    }
    parent = parent.parentElement
  }
  return true
}

function stillOverNumber(anchor: HTMLElement) {
  if (!anchorVisible(anchor)) return false
  if (document.activeElement === anchor) return true
  return pointerHits(anchor)
}

/**
 * Compact metric with the exact value in a tooltip.
 * The tip is portaled so table overflow does not clip it. It closes as soon
 * as the pointer leaves the number, including when a scroll box moves the
 * number out from under the cursor, so it cannot drift across the page.
 */
export default function UsageMetricValue({
  display,
  exact,
  className = '',
}: UsageMetricValueProps) {
  const id = useId()
  const anchorRef = useRef<HTMLSpanElement>(null)
  const tipRef = useRef<HTMLSpanElement>(null)
  const [open, setOpen] = useState(false)
  const reveal = Boolean(exact) && exact !== display

  const close = () => {
    setOpen(false)
    if (activeId === id) setActive(null)
  }

  useEffect(() => {
    const onActive = (next: string | null) => {
      if (next !== id) setOpen(false)
    }
    activeListeners.add(onActive)
    return () => {
      activeListeners.delete(onActive)
      if (activeId === id) activeId = null
    }
  }, [id])

  useLayoutEffect(() => {
    if (!open) return
    const anchor = anchorRef.current
    const tip = tipRef.current
    if (!anchor || !tip || !anchorVisible(anchor)) return
    placeTooltip(anchor, tip)
  }, [open])

  useEffect(() => {
    if (!open) return
    const sync = () => {
      const anchor = anchorRef.current
      const tip = tipRef.current
      if (!anchor || !tip || !stillOverNumber(anchor)) {
        close()
        return
      }
      placeTooltip(anchor, tip)
    }
    const onPointerMove = (event: PointerEvent) => {
      pointer = { x: event.clientX, y: event.clientY }
      sync()
    }
    window.addEventListener('scroll', sync, true)
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('resize', sync)
    return () => {
      window.removeEventListener('scroll', sync, true)
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('resize', sync)
    }
  }, [open])

  return (
    <span
      ref={anchorRef}
      className={`tabular-nums whitespace-nowrap ${reveal ? 'cursor-help' : ''} ${className}`}
      aria-label={reveal ? exact : undefined}
      onMouseEnter={(event) => {
        if (!reveal) return
        pointer = { x: event.clientX, y: event.clientY }
        setActive(id)
        setOpen(true)
      }}
      onMouseLeave={close}
      onFocus={() => {
        if (!reveal) return
        setActive(id)
        setOpen(true)
      }}
      onBlur={close}
      tabIndex={reveal ? 0 : undefined}
    >
      {display}
      {open && reveal && typeof document !== 'undefined'
        ? createPortal(
          <span
            ref={tipRef}
            role="tooltip"
            className="pointer-events-none whitespace-nowrap rounded-md bg-gray-900 px-2 py-1 text-xs font-medium text-white shadow-lg"
            style={{ position: 'fixed', zIndex: 80, top: 0, left: 0, visibility: 'hidden' }}
          >
            {exact}
          </span>,
          document.body,
        )
        : null}
    </span>
  )
}
