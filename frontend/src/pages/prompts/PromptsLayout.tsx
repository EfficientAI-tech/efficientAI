import { Outlet } from 'react-router-dom'
import PromptsTabBar from './PromptsTabBar'

export default function PromptsLayout() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Prompts</h1>
        <p className="mt-2 text-sm text-gray-600 max-w-2xl">
          Manage reusable prompt partials, run GEPA optimization, and align
          LLM-as-a-judge evaluators against human-labeled data.
        </p>
      </div>
      <PromptsTabBar />
      <Outlet />
    </div>
  )
}
