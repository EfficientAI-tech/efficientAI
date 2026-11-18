import { Outlet } from 'react-router-dom'
import PromptsTabBar from './PromptsTabBar'
import { PROMPTS_HEADER_ACTIONS_SLOT_ID } from './promptsHeaderSlot'

export default function PromptsLayout() {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-bold text-gray-900">Prompts</h1>
          <p className="mt-1 text-sm text-gray-600 max-w-3xl">
            Reusable prompt partials, optimization runs, and LLM-judge alignment in one place.
          </p>
        </div>
        <div
          id={PROMPTS_HEADER_ACTIONS_SLOT_ID}
          className="flex shrink-0 flex-wrap items-center justify-end gap-2"
        />
      </div>
      <PromptsTabBar />
      <Outlet />
    </div>
  )
}
