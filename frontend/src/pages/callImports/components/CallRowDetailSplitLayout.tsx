import type { ReactNode } from 'react'

/**
 * When a row detail panel is open, pin it in the right column and scroll
 * only the list/table on the left so the panel never scrolls off-screen.
 */
export function CallRowDetailSplitLayout({
  panelOpen,
  list,
  panel,
}: {
  panelOpen: boolean
  list: ReactNode
  panel: ReactNode | null
}) {
  if (!panelOpen || !panel) {
    return <>{list}</>
  }

  return (
    <div className="flex items-stretch gap-4 h-[calc(100vh-11rem)] min-h-[20rem]">
      <div className="min-w-0 flex-1 overflow-y-auto overscroll-contain">{list}</div>
      <div className="w-full max-w-[42rem] shrink-0 min-h-0 flex flex-col">{panel}</div>
    </div>
  )
}
