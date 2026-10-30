import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FlaskConical, MessageSquare } from 'lucide-react'
import Button from '../../../components/Button'
import { sandboxApi, type SessionKind } from '../../../lib/sandbox'
import { SandboxSessionTable } from './SandboxSessionTable'

export default function SandboxTab() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<'all' | SessionKind>('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [hasIssuesOnly, setHasIssuesOnly] = useState(false)
  const items = sandboxApi.listSessions()

  const filtered = useMemo(() => {
    return items.filter((item) => {
      if (typeFilter !== 'all' && item.kind !== typeFilter) return false
      if (hasIssuesOnly && item.openErrorCount + item.openWarningCount === 0) return false
      if (search && !item.id.toLowerCase().includes(search.toLowerCase())) return false
      if (statusFilter === 'running') {
        return ['running', 'queued', 'evaluating', 'active'].includes(item.status)
      }
      if (statusFilter === 'completed') {
        return ['completed', 'ended', 'idle'].includes(item.status)
      }
      if (statusFilter === 'failed') return item.status === 'failed'
      return true
    })
  }, [items, typeFilter, statusFilter, hasIssuesOnly, search])

  return (
    <div className="mt-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Agent sandbox</h2>
          <p className="text-xs text-gray-500">
            Run two agents against each other, or chat with the main agent in a simulated environment.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            leftIcon={<MessageSquare className="h-4 w-4" />}
            onClick={() => navigate('/playground/sandbox/new-chat')}
          >
            New manual chat
          </Button>
          <Button
            size="sm"
            leftIcon={<FlaskConical className="h-4 w-4" />}
            onClick={() => navigate('/playground/sandbox/new')}
          >
            New simulation
          </Button>
        </div>
      </div>
      {items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 p-10 text-center">
          <p className="text-sm text-gray-600">No sandbox sessions yet.</p>
          <div className="mt-4 flex justify-center gap-2">
            <Button onClick={() => navigate('/playground/sandbox/new')}>New simulation</Button>
            <Button variant="outline" onClick={() => navigate('/playground/sandbox/new-chat')}>
              New manual chat
            </Button>
          </div>
        </div>
      ) : (
        <SandboxSessionTable
          items={filtered}
          search={search}
          onSearch={setSearch}
          typeFilter={typeFilter}
          onTypeFilter={setTypeFilter}
          statusFilter={statusFilter}
          onStatusFilter={setStatusFilter}
          hasIssuesOnly={hasIssuesOnly}
          onHasIssuesOnly={setHasIssuesOnly}
          onOpen={(id) => navigate(`/playground/sandbox/${id}`)}
        />
      )}
    </div>
  )
}
