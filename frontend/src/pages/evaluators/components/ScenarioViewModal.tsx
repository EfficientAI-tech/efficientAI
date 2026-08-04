import { createPortal } from 'react-dom'
import { FileText, X } from 'lucide-react'
import Button from '../../../components/Button'
import { EvaluatorSuiteCombination } from '../../../lib/api'

interface Props {
  combination: EvaluatorSuiteCombination | null
  onClose: () => void
}

export default function ScenarioViewModal({ combination, onClose }: Props) {
  if (!combination) return null

  const modal = (
    <div className="fixed inset-0 z-[9999] overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center p-4">
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" onClick={onClose} />
        <div className="relative bg-white rounded-lg shadow-xl w-full max-w-lg max-h-[85vh] flex flex-col">
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-9 h-9 rounded-lg bg-green-50 flex items-center justify-center shrink-0">
                <FileText className="h-4 w-4 text-green-600" />
              </div>
              <h2 className="text-lg font-semibold text-gray-900 truncate">
                {combination.scenario_name || 'Scenario'}
              </h2>
            </div>
            <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1 rounded-lg hover:bg-gray-100">
              <X className="h-5 w-5" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
            {combination.scenario_description ? (
              <div>
                <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Description</h3>
                <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap rounded-xl border border-gray-100 bg-gray-50/50 p-4">
                  {combination.scenario_description}
                </p>
              </div>
            ) : (
              <p className="text-sm text-gray-500 italic">No description provided.</p>
            )}
            {combination.scenario_required_info && Object.keys(combination.scenario_required_info).length > 0 && (
              <div>
                <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Required info / script</h3>
                <pre className="text-xs bg-gray-900 text-gray-100 rounded-xl p-4 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed">
                  {JSON.stringify(combination.scenario_required_info, null, 2)}
                </pre>
              </div>
            )}
          </div>
          <div className="px-6 py-4 border-t border-gray-200 bg-gray-50 rounded-b-lg flex justify-end">
            <Button variant="outline" onClick={onClose}>Close</Button>
          </div>
        </div>
      </div>
    </div>
  )

  if (typeof document === 'undefined') return null
  return createPortal(modal, document.body)
}
