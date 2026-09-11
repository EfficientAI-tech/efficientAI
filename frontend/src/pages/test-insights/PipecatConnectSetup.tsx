import { Link } from 'react-router-dom'
import { Check, Copy } from 'lucide-react'
import { useState } from 'react'

type SetupStep = { title: string; detail: string }
type SetupSection = { part: string; title: string; subtitle?: string; steps: SetupStep[] }
type IntegrationPiece = { piece: string; role: string }
type TroubleshootingRow = { symptom: string; fix: string }

export type PipecatSetupData = {
  setup_intro?: string
  docs_url?: string
  setup_sections?: SetupSection[]
  env_block?: string
  install_command?: string
  bot_imports_snippet?: string
  pipecat_python_example?: string
  run_command?: string
  test_client_url?: string
  example_bot_path?: string
  setup_checklist?: string[]
  integration_pieces?: IntegrationPiece[]
  troubleshooting?: TroubleshootingRow[]
  otlp_endpoint?: string
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* ignore */
    }
  }

  return (
    <button
      type="button"
      onClick={() => void handleCopy()}
      className="inline-flex items-center gap-1.5 text-xs font-medium text-primary-600 hover:text-primary-800"
    >
      {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
      {copied ? 'Copied' : label}
    </button>
  )
}

function CodeBlock({ code, copyLabel }: { code: string; copyLabel: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
      <div className="flex items-center justify-between gap-2 px-4 py-2 border-b border-gray-100 bg-gray-50">
        <CopyButton text={code} label={copyLabel} />
      </div>
      <pre className="text-xs font-mono text-slate-100 bg-slate-900 p-4 overflow-x-auto whitespace-pre-wrap">
        {code}
      </pre>
    </div>
  )
}

type PipecatConnectSetupProps = {
  setup: PipecatSetupData
  envBlock: string
  onGoToCalls: () => void
}

export default function PipecatConnectSetup({ setup, envBlock, onGoToCalls }: PipecatConnectSetupProps) {
  const sections = setup.setup_sections ?? []

  return (
    <div className="divide-y divide-gray-200">
      <div className="px-6 py-5 bg-gradient-to-br from-primary-50/80 to-white">
        <h2 className="text-lg font-semibold text-gray-900">Connect Pipecat — from scratch</h2>
        {setup.setup_intro && (
          <p className="text-sm text-gray-600 mt-2 max-w-3xl leading-relaxed">{setup.setup_intro}</p>
        )}
        <p className="text-sm text-gray-600 mt-3">
          <Link to="/settings" className="text-primary-600 hover:text-primary-800 font-medium">
            Settings → API keys
          </Link>
          {setup.docs_url && (
            <>
              {' · '}
              <a
                href={setup.docs_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary-600 hover:text-primary-800 font-medium"
              >
                Full documentation
              </a>
            </>
          )}
        </p>
      </div>

      {sections.map((section) => (
        <div key={section.part} className="px-6 py-5">
          <div className="flex items-start gap-3 mb-4">
            <span className="flex-shrink-0 w-8 h-8 rounded-full bg-primary-100 text-primary-800 text-sm font-semibold flex items-center justify-center">
              {section.part}
            </span>
            <div>
              <h3 className="text-sm font-semibold text-gray-900">{section.title}</h3>
              {section.subtitle && (
                <p className="text-sm text-gray-500 mt-0.5">{section.subtitle}</p>
              )}
            </div>
          </div>
          <ol className="space-y-3 ml-11">
            {section.steps.map((step, index) => (
              <li key={`${section.part}-${index}`} className="text-sm">
                <span className="font-medium text-gray-900">{step.title}</span>
                <p className="text-gray-600 mt-0.5 leading-relaxed">{step.detail}</p>
              </li>
            ))}
          </ol>

          {section.part === '2' && envBlock && (
            <div className="mt-5 ml-11 space-y-4">
              <div>
                <p className="text-xs font-medium text-gray-500 mb-2">Pipecat .env file</p>
                <CodeBlock code={envBlock} copyLabel="Copy .env" />
              </div>
              {setup.install_command && (
                <div>
                  <p className="text-xs font-medium text-gray-500 mb-2">Install (run once in Pipecat folder)</p>
                  <CodeBlock code={setup.install_command} copyLabel="Copy install commands" />
                </div>
              )}
            </div>
          )}

          {section.part === '3' && (
            <div className="mt-5 ml-11 space-y-4">
              {setup.bot_imports_snippet && (
                <div>
                  <p className="text-xs font-medium text-gray-500 mb-2">Imports — top of bot.py</p>
                  <CodeBlock code={setup.bot_imports_snippet} copyLabel="Copy imports" />
                </div>
              )}
              {setup.pipecat_python_example && (
                <div>
                  <p className="text-xs font-medium text-gray-500 mb-2">Three hooks — inside run_bot()</p>
                  <CodeBlock code={setup.pipecat_python_example} copyLabel="Copy hooks" />
                </div>
              )}
              {setup.example_bot_path && (
                <p className="text-sm text-gray-600">
                  Full example:{' '}
                  <span className="font-mono text-xs bg-gray-100 px-1.5 py-0.5 rounded">
                    {setup.example_bot_path}
                  </span>
                </p>
              )}
            </div>
          )}

          {section.part === '4' && (
            <div className="mt-5 ml-11 space-y-3">
              {setup.run_command && (
                <div className="flex flex-wrap items-center gap-2 text-sm text-gray-700">
                  <span>Run:</span>
                  <code className="font-mono text-xs bg-gray-100 px-2 py-1 rounded">{setup.run_command}</code>
                  <CopyButton text={setup.run_command} label="Copy" />
                </div>
              )}
              {setup.test_client_url && (
                <div className="flex flex-wrap items-center gap-2 text-sm text-gray-700">
                  <span>Test client:</span>
                  <a
                    href={setup.test_client_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-mono text-xs text-primary-600 hover:text-primary-800"
                  >
                    {setup.test_client_url}
                  </a>
                </div>
              )}
              <button
                type="button"
                onClick={onGoToCalls}
                className="inline-flex items-center text-sm font-medium text-primary-600 hover:text-primary-800"
              >
                Go to Calls tab → Refresh after your test
              </button>
            </div>
          )}
        </div>
      ))}

      {(setup.integration_pieces ?? []).length > 0 && (
        <div className="px-6 py-5 bg-gray-50">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">What each piece does</h3>
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                <tr>
                  <th className="px-4 py-2">Piece</th>
                  <th className="px-4 py-2">Role</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {setup.integration_pieces!.map((row) => (
                  <tr key={row.piece}>
                    <td className="px-4 py-2 font-mono text-xs text-gray-900 whitespace-nowrap">
                      {row.piece}
                    </td>
                    <td className="px-4 py-2 text-gray-600">{row.role}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {(setup.setup_checklist ?? []).length > 0 && (
        <div className="px-6 py-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Checklist</h3>
          <ul className="space-y-2">
            {setup.setup_checklist!.map((item) => (
              <li key={item} className="flex items-start gap-2 text-sm text-gray-700">
                <span className="mt-0.5 w-4 h-4 rounded border border-gray-300 flex-shrink-0" aria-hidden />
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}

      {(setup.troubleshooting ?? []).length > 0 && (
        <div className="px-6 py-5 bg-amber-50/50">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">If something fails</h3>
          <div className="overflow-x-auto rounded-lg border border-amber-200/80 bg-white">
            <table className="min-w-full text-sm">
              <thead className="bg-amber-50/80 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                <tr>
                  <th className="px-4 py-2">Symptom</th>
                  <th className="px-4 py-2">Check</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {setup.troubleshooting!.map((row) => (
                  <tr key={row.symptom}>
                    <td className="px-4 py-2 text-gray-900">{row.symptom}</td>
                    <td className="px-4 py-2 text-gray-600">{row.fix}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {setup.otlp_endpoint && (
        <div className="px-6 py-4 bg-gray-50 text-xs text-gray-500">
          <span className="font-medium text-gray-600">Advanced:</span> OTLP export URL{' '}
          <span className="font-mono break-all">{setup.otlp_endpoint}</span>
        </div>
      )}
    </div>
  )
}
