import { useState, type ReactNode } from 'react'
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { SortableContext, horizontalListSortingStrategy, verticalListSortingStrategy } from '@dnd-kit/sortable'
import AddWidgetButton from './AddWidgetButton'
import AgentsTableWidget from './AgentsTableWidget'
import { locateWidget, useDashboardLayout, type LayoutZone } from './dashboardLayout'
import WidgetCard from './WidgetCard'

export default function DashboardCanvas() {
  const topBar = useDashboardLayout((s) => s.topBar)
  const rows = useDashboardLayout((s) => s.rows)
  const rail = useDashboardLayout((s) => s.rail)
  const moveWidget = useDashboardLayout((s) => s.moveWidget)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))
  const [railHover, setRailHover] = useState(false)
  const [railPinned, setRailPinned] = useState(false)
  const [dragging, setDragging] = useState(false)
  const railOpen = railHover || railPinned || dragging

  const onDragEnd = (event: DragEndEvent) => {
    setDragging(false)
    const activeId = String(event.active.id)
    const overId = event.over ? String(event.over.id) : null
    if (!overId || activeId === overId) return
    if (overId.startsWith('zone:')) {
      moveWidget(activeId, { zone: overId.slice(5) as LayoutZone, index: 999 })
      return
    }
    const dest = locateWidget({ topBar, rows, rail }, overId)
    if (dest) moveWidget(activeId, { zone: dest.zone, index: dest.index })
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={() => setDragging(true)}
      onDragCancel={() => setDragging(false)}
      onDragEnd={onDragEnd}
    >
      <div className="relative flex min-h-[calc(100vh-11rem)] flex-col space-y-4 pr-8">
        <Zone id="topBar" className="group/row">
          <SortableContext items={topBar.map((item) => item.id)} strategy={horizontalListSortingStrategy}>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {topBar.map((widget) => (
                <WidgetCard key={widget.id} widget={widget} compact="top" />
              ))}
            </div>
          </SortableContext>
          <AddWidgetButton zone="topBar" />
        </Zone>

        <div className="relative min-w-0 flex-1 space-y-4">
          <div className="pointer-events-none absolute -inset-4 rounded-[32px] bg-gradient-to-br from-indigo-100/90 via-sky-50/75 to-amber-100/85" />
          <div className="pointer-events-none absolute -right-8 top-10 h-48 w-48 rounded-full bg-fuchsia-200/50 blur-3xl" />
          <div className="pointer-events-none absolute left-8 top-28 h-36 w-36 rounded-full bg-cyan-200/50 blur-3xl" />
          <div className="pointer-events-none absolute bottom-10 right-1/4 h-40 w-40 rounded-full bg-orange-200/40 blur-3xl" />
          {rows.map((row, rowIndex) => (
            <Zone key={`row-${rowIndex}`} id={`row:${rowIndex}`} className="relative group/row">
              <SortableContext items={row.map((item) => item.id)} strategy={horizontalListSortingStrategy}>
                <div className={`grid grid-cols-1 gap-4 ${row.length >= 3 ? 'xl:grid-cols-2 2xl:grid-cols-3' : row.length === 2 ? 'xl:grid-cols-2' : ''}`}>
                  {row.map((widget) => (
                    <WidgetCard key={widget.id} widget={widget} />
                  ))}
                </div>
              </SortableContext>
              {row.length < 3 && <AddWidgetButton zone={`row:${rowIndex}`} />}
            </Zone>
          ))}
          <Zone id={`row:${rows.length}`} className="relative group/row min-h-[2rem]">
            <AddWidgetButton zone={`row:${rows.length}`} />
          </Zone>
          <div className="relative flex min-h-0 flex-1 flex-col">
            <AgentsTableWidget />
          </div>
        </div>

        <IndexOverlay
          open={railOpen}
          pinned={railPinned}
          onHover={setRailHover}
          onTogglePin={() => setRailPinned((value) => !value)}
        >
          <Zone id="rail" className="group/row space-y-2">
            <SortableContext items={rail.map((item) => item.id)} strategy={verticalListSortingStrategy}>
              <div className="space-y-2">
                {rail.map((widget) => (
                  <WidgetCard key={widget.id} widget={widget} compact="rail" />
                ))}
              </div>
            </SortableContext>
            <AddWidgetButton zone="rail" />
          </Zone>
        </IndexOverlay>
      </div>
    </DndContext>
  )
}

function IndexOverlay({
  open,
  pinned,
  onHover,
  onTogglePin,
  children,
}: {
  open: boolean
  pinned: boolean
  onHover: (value: boolean) => void
  onTogglePin: () => void
  children: ReactNode
}) {
  return (
    <div className="pointer-events-none fixed right-0 top-28 z-30">
      <div
        className="pointer-events-auto flex max-h-[calc(100vh-8rem)] items-start"
        onMouseEnter={() => onHover(true)}
        onMouseLeave={() => onHover(false)}
      >
        <aside
          className={`overflow-hidden rounded-l-xl border shadow-xl backdrop-blur transition-all duration-200 ${
            open
              ? 'w-[240px] border-indigo-200 bg-gradient-to-b from-indigo-50/95 to-white/95 p-3 opacity-100'
              : 'w-0 border-transparent p-0 opacity-0 shadow-none'
          }`}
        >
          <div className="mb-2 flex items-center justify-between px-1">
            <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-indigo-400">Index</p>
            <button
              type="button"
              onClick={onTogglePin}
              className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                pinned ? 'bg-gray-900 text-white' : 'text-gray-400 hover:text-gray-700'
              }`}
            >
              {pinned ? 'Pinned' : 'Pin'}
            </button>
          </div>
          <div className="max-h-[calc(100vh-12rem)] overflow-y-auto pr-0.5">{children}</div>
        </aside>
        <button
          type="button"
          onClick={onTogglePin}
          aria-expanded={open}
          aria-label="Index metrics"
          className={`flex h-32 w-8 items-center justify-center rounded-l-lg border border-r-0 shadow-sm transition ${
            open
              ? 'border-indigo-200 bg-indigo-600 text-white'
              : 'border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-100'
          }`}
        >
          <span
            className="text-[11px] font-semibold uppercase tracking-[0.16em]"
            style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}
          >
            Index
          </span>
        </button>
      </div>
    </div>
  )
}

function Zone({ id, className, children }: { id: LayoutZone; className?: string; children: ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: `zone:${id}` })
  return (
    <div
      ref={setNodeRef}
      className={`${className ?? ''} ${isOver ? 'rounded-xl ring-2 ring-indigo-200' : ''}`}
    >
      {children}
    </div>
  )
}
