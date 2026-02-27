import { Lock, Mail, ExternalLink } from 'lucide-react'

const FEATURE_LABELS: Record<string, { title: string }> = {
  voice_playground: { title: 'Voice Playground' },
}

const FALLBACK_TITLE = 'Enterprise Feature'

export default function EnterpriseUpgrade({ feature }: { feature: string }) {
  const title = FEATURE_LABELS[feature]?.title ?? FALLBACK_TITLE

  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="max-w-lg w-full text-center px-6">
        <div className="mx-auto flex items-center justify-center h-16 w-16 rounded-full bg-amber-50 mb-6">
          <Lock className="h-8 w-8 text-amber-600" />
        </div>

        <h1 className="text-2xl font-bold text-gray-900 mb-2">{title}</h1>

        <span className="inline-block text-xs font-semibold uppercase tracking-wider text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-3 py-1 mb-4">
          Enterprise Feature
        </span>

        <p className="text-gray-600 mb-8 leading-relaxed">
          This feature is available with an EfficientAI Enterprise license.
        </p>

        <div className="bg-gray-50 border border-gray-200 rounded-xl p-6 mb-8 text-left">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">
            To unlock this feature:
          </h3>
          <ol className="space-y-2 text-sm text-gray-600">
            <li className="flex items-start gap-2">
              <span className="flex-shrink-0 font-semibold text-gray-900">1.</span>
              Contact the EfficientAI team for an enterprise license key
            </li>
            <li className="flex items-start gap-2">
              <span className="flex-shrink-0 font-semibold text-gray-900">2.</span>
              Set the <code className="bg-gray-200 px-1.5 py-0.5 rounded text-xs font-mono">EFFICIENTAI_LICENSE</code> environment variable on your server
            </li>
            <li className="flex items-start gap-2">
              <span className="flex-shrink-0 font-semibold text-gray-900">3.</span>
              Restart the EfficientAI backend to activate
            </li>
          </ol>
        </div>

        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <a
            href="mailto:sales@efficientai.com?subject=Enterprise%20License%20Inquiry"
            className="inline-flex items-center justify-center gap-2 px-5 py-2.5 text-sm font-medium text-white bg-gray-900 rounded-lg hover:bg-gray-800 transition-colors"
          >
            <Mail className="h-4 w-4" />
            Contact Sales
          </a>
          <a
            href="https://www.efficientai.com/enterprise"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center gap-2 px-5 py-2.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            <ExternalLink className="h-4 w-4" />
            Learn More
          </a>
        </div>
      </div>
    </div>
  )
}
