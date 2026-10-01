import { useEffect, useState, type CSSProperties, type RefObject } from 'react'

export type AnchoredMenuPosition = {
  top: number
  left: number
  width: number
  maxHeight: number
  style: CSSProperties
}

const VIEWPORT_MARGIN = 8
const GAP = 4
const DEFAULT_MAX = 280

export function useAnchoredMenuPosition(
  open: boolean,
  anchorRef: RefObject<HTMLElement | null>,
  options?: { maxHeight?: number },
): AnchoredMenuPosition | null {
  const preferredMax = options?.maxHeight ?? DEFAULT_MAX
  const [position, setPosition] = useState<AnchoredMenuPosition | null>(null)

  useEffect(() => {
    if (!open || !anchorRef.current) {
      setPosition(null)
      return
    }

    const update = () => {
      const anchor = anchorRef.current
      if (!anchor) return
      const rect = anchor.getBoundingClientRect()
      const spaceBelow = window.innerHeight - rect.bottom - VIEWPORT_MARGIN
      const spaceAbove = rect.top - VIEWPORT_MARGIN
      const openUp = spaceBelow < 160 && spaceAbove > spaceBelow
      const maxHeight = Math.max(
        120,
        Math.min(preferredMax, openUp ? spaceAbove - GAP : spaceBelow - GAP),
      )
      const top = openUp ? rect.top - GAP : rect.bottom + GAP
      setPosition({
        top,
        left: rect.left,
        width: rect.width,
        maxHeight,
        style: {
          position: 'fixed',
          top,
          left: rect.left,
          width: rect.width,
          maxHeight,
          zIndex: 10050,
          transform: openUp ? 'translateY(-100%)' : undefined,
        },
      })
    }

    update()
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)
    return () => {
      window.removeEventListener('resize', update)
      window.removeEventListener('scroll', update, true)
    }
  }, [open, anchorRef, preferredMax])

  return position
}
