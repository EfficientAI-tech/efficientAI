import { useEffect, useState, type RefObject } from 'react'

type Coords = { top: number; left: number; width: number }

export function useAnchoredDropdown(
  open: boolean,
  anchorRef: RefObject<HTMLElement | null>,
): Coords | null {
  const [coords, setCoords] = useState<Coords | null>(null)

  useEffect(() => {
    if (!open || !anchorRef.current) {
      setCoords(null)
      return
    }

    const update = () => {
      if (!anchorRef.current) return
      const rect = anchorRef.current.getBoundingClientRect()
      setCoords({
        top: rect.bottom + 4,
        left: rect.left,
        width: rect.width,
      })
    }

    update()
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)
    return () => {
      window.removeEventListener('resize', update)
      window.removeEventListener('scroll', update, true)
    }
  }, [open, anchorRef])

  return coords
}
