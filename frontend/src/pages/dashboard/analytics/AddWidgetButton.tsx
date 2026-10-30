import { useState } from 'react'
import { Plus } from 'lucide-react'
import { WIDGET_META, WIDGET_TYPES, type LayoutZone, type WidgetType, useDashboardLayout } from './dashboardLayout'

export default function AddWidgetButton({ zone }: { zone: LayoutZone }) {
  const addWidget = useDashboardLayout((s) => s.addWidget)
  const [open, setOpen] = useState(false)
  return (
    <div className="relative flex items-center">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex h-8 w-8 items-center justify-center rounded-full border border-dashed border-gray-300 text-gray-400 opacity-0 transition hover:border-gray-500 hover:text-gray-700 group-hover/row:opacity-100"
        aria-label="Add widget"
      >
        <Plus className="h-4 w-4" />
      </button>
      {open && (
        <div className="absolute left-0 top-9 z-20 max-h-64 w-48 overflow-y-auto rounded-lg border border-gray-200 bg-white py-1 text-xs shadow-lg">
          {WIDGET_TYPES.map((type: WidgetType) => (
            <button
              key={type}
              type="button"
              onClick={() => {
                addWidget(type, zone)
                setOpen(false)
              }}
              className="block w-full px-2.5 py-1.5 text-left text-gray-700 hover:bg-gray-50"
            >
              {WIDGET_META[type].label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
