import { Link } from 'react-router-dom'
import { BarChart3, Mic, Plus, Activity } from 'lucide-react'
import { Button } from '@heroui/react'

export default function QuickActionsBar() {
  const actions = [
    { label: 'New Evaluation', href: '/metrics', icon: Plus },
    { label: 'Voice Bundles', href: '/voicebundles', icon: Mic },
    { label: 'Observability', href: '/observability', icon: Activity },
    { label: 'Results', href: '/results', icon: BarChart3 },
  ]

  return (
    <div className="flex flex-wrap gap-2">
      {actions.map(({ label, href, icon: Icon }) => (
        <Button
          key={href}
          as={Link}
          to={href}
          size="sm"
          variant="flat"
          className="bg-white/80 border border-gray-200 text-gray-700 font-medium"
          startContent={<Icon className="w-4 h-4" />}
        >
          {label}
        </Button>
      ))}
    </div>
  )
}
