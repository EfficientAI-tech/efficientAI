import { Sparkles, Headphones } from 'lucide-react'
import { useVoicePlayground } from '../context'

export default function ModeChooser() {
  const { mode, setMode } = useVoicePlayground()

  const options = [
    {
      key: 'benchmark' as const,
      icon: Sparkles,
      title: 'Run Benchmark',
      description:
        'Generate TTS audio (or use existing recordings/uploads) for sample texts and compare A vs B.',
      color: 'blue',
    },
    {
      key: 'blind_test_only' as const,
      icon: Headphones,
      title: 'Create Blind Test',
      description:
        'Skip TTS generation. Pair existing recordings, uploads, or past TTS samples and share for blind rating.',
      color: 'purple',
    },
  ]

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 mb-4">
      <p className="text-sm font-medium text-gray-700 mb-3">What would you like to do?</p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {options.map((opt) => {
          const Icon = opt.icon
          const active = mode === opt.key
          const activeRing =
            opt.color === 'blue'
              ? 'ring-2 ring-blue-500 bg-blue-50 border-blue-300'
              : 'ring-2 ring-purple-500 bg-purple-50 border-purple-300'
          const iconBg = opt.color === 'blue' ? 'bg-blue-100 text-blue-600' : 'bg-purple-100 text-purple-600'
          return (
            <button
              key={opt.key}
              onClick={() => setMode(opt.key)}
              className={`text-left rounded-xl border p-4 transition-all ${
                active ? activeRing : 'border-gray-200 bg-white hover:bg-gray-50'
              }`}
            >
              <div className="flex items-start gap-3">
                <span className={`w-9 h-9 rounded-lg flex items-center justify-center ${iconBg}`}>
                  <Icon className="w-5 h-5" />
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-900">{opt.title}</p>
                  <p className="text-xs text-gray-600 mt-1">{opt.description}</p>
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
