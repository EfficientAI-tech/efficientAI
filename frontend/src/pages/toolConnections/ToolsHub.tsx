import { useSearchParams } from 'react-router-dom'
import { BookOpen, Plug, Wrench } from 'lucide-react'
import { KnowledgeBases } from '../knowledgeBases'
import ToolConnections from './ToolConnections'

const TABS = [
  { id: 'connections', label: 'Connections', icon: Plug },
  { id: 'knowledge-bases', label: 'Knowledge bases', icon: BookOpen },
] as const

type TabId = (typeof TABS)[number]['id']

/** Everything agents can call or search: tool connections and knowledge bases (``?tab=``). */
export default function ToolsHub() {
  const [params, setParams] = useSearchParams()
  const tab: TabId = params.get('tab') === 'knowledge-bases' ? 'knowledge-bases' : 'connections'

  return (
    <div className="flex h-full flex-col bg-white">
      <div className="px-6 pt-4">
        <div className="flex items-center gap-2">
          <Wrench className="h-5 w-5 text-primary-600" />
          <h1 className="text-xl font-semibold text-gray-900">Tools</h1>
        </div>
        <div className="mt-3 flex gap-1 border-b border-gray-200" role="tablist" aria-label="Tools sections">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => setParams(id === 'connections' ? {} : { tab: id }, { replace: true })}
              className={`-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium ${
                tab === id
                  ? 'border-primary-500 text-gray-900'
                  : 'border-transparent text-gray-500 hover:text-gray-800'
              }`}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1">
        {tab === 'knowledge-bases' ? <KnowledgeBases embedded /> : <ToolConnections embedded />}
      </div>
    </div>
  )
}
