import ReactMarkdown from 'react-markdown'
import { format } from 'date-fns'
import { VoiceBundle, Integration } from '../../../types/api'

interface Agent {
  id: string
  name: string
  phone_number?: string | null
  language: string
  description?: string | null
  call_type: string
  call_medium: string
  created_at: string
  updated_at: string
  voice_bundle_id?: string | null
  voice_ai_integration_id?: string | null
  voice_ai_agent_id?: string | null
}

interface AgentInfoViewProps {
  agent: Agent
  voiceBundles: VoiceBundle[]
  integrations: Integration[]
}

const LANGUAGE_LABELS: Record<string, string> = {
  en: 'English',
  es: 'Spanish',
  fr: 'French',
  de: 'German',
  zh: 'Chinese',
  hi: 'Hindi',
}

export default function AgentInfoView({
  agent,
  voiceBundles,
  integrations,
}: AgentInfoViewProps) {
  return (
    <div className="overflow-x-auto">
      <div className="grid grid-cols-2 gap-6 min-w-[1100px]">
        <div className="min-w-0 space-y-8">
          {/* General Information */}
          <div>
            <h3 className="text-lg font-medium text-gray-900 border-b border-gray-200 pb-2 mb-4">
              General Information
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <dt className="text-sm font-medium text-gray-500">Created</dt>
                <dd className="mt-1 text-sm text-gray-900">{format(new Date(agent.created_at), 'PPpp')}</dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-gray-500">Last Updated</dt>
                <dd className="mt-1 text-sm text-gray-900">{format(new Date(agent.updated_at), 'PPpp')}</dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-gray-500">Name</dt>
                <dd className="mt-1 text-sm text-gray-900 font-medium">{agent.name}</dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-gray-500">Language</dt>
                <dd className="mt-1 text-sm text-gray-900">
                  {LANGUAGE_LABELS[agent.language] || agent.language}
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-gray-500">Call Type</dt>
                <dd className="mt-1 text-sm text-gray-900 capitalize">{agent.call_type}</dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-gray-500">Call Medium</dt>
                <dd className="mt-1 text-sm text-gray-900 capitalize flex items-center gap-2">
                  {agent.call_medium === 'phone_call' ? 'Phone Call' : 'Web Call'}
                </dd>
              </div>
              {agent.phone_number && (
                <div>
                  <dt className="text-sm font-medium text-gray-500">Phone Number</dt>
                  <dd className="mt-1 text-sm text-gray-900">{agent.phone_number}</dd>
                </div>
              )}
            </div>
          </div>

          {/* Voice Configuration */}
          <div>
            <h3 className="text-lg font-medium text-gray-900 border-b border-gray-200 pb-2 mb-4">
              Voice Configuration
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Test Voice Agent */}
              <div className="border border-gray-200 rounded-lg p-4 bg-gray-50 h-full">
                <div className="flex items-center justify-between mb-3">
                  <h4 className="text-base font-semibold text-gray-900">Test Voice Agent</h4>
                </div>
                {agent.voice_bundle_id ? (
                  <div>
                    <dt className="text-sm font-medium text-gray-500">Voice Bundle</dt>
                    <dd className="mt-1 text-sm text-gray-900 font-medium bg-blue-50 text-blue-700 px-3 py-1 rounded-md inline-block border border-blue-100">
                      {voiceBundles.find((v) => v.id === agent.voice_bundle_id)?.name ||
                        agent.voice_bundle_id}
                    </dd>
                  </div>
                ) : (
                  <p className="text-sm text-gray-500 italic">No test voice bundle configured.</p>
                )}
              </div>

              {/* Voice AI Agent */}
              <div className="border border-gray-200 rounded-lg p-4 bg-gray-50 h-full">
                <div className="flex items-center justify-between mb-3">
                  <h4 className="text-base font-semibold text-gray-900">Voice AI Agent</h4>
                </div>
                {agent.voice_ai_integration_id && agent.voice_ai_agent_id ? (
                  <div className="grid grid-cols-1 gap-4">
                    <div>
                      <dt className="text-sm font-medium text-gray-500">Integration Provider</dt>
                      <dd className="mt-1 flex items-center gap-2">
                        {(() => {
                          const integration = integrations.find(
                            (i) => i.id === agent.voice_ai_integration_id
                          )
                          if (integration?.platform === 'retell') {
                            return (
                              <>
                                <img
                                  src="/retellai.png"
                                  alt="Retell"
                                  className="h-6 w-6 object-contain"
                                />
                                <span className="text-base font-medium text-gray-900">
                                  Retell AI
                                </span>
                              </>
                            )
                          } else if (integration?.platform === 'vapi') {
                            return (
                              <>
                                <img
                                  src="/vapiai.jpg"
                                  alt="Vapi"
                                  className="h-6 w-6 rounded-full object-contain"
                                />
                                <span className="text-base font-medium text-gray-900">Vapi AI</span>
                              </>
                            )
                          } else if (integration?.platform === 'elevenlabs') {
                            return (
                              <>
                                <img
                                  src="/elevenlabs.jpg"
                                  alt="ElevenLabs"
                                  className="h-6 w-6 rounded-full object-contain"
                                />
                                <span className="text-base font-medium text-gray-900">
                                  ElevenLabs
                                </span>
                              </>
                            )
                          }
                          return (
                            <span className="text-sm text-gray-900">
                              {integration?.name || 'Unknown Provider'}
                            </span>
                          )
                        })()}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-sm font-medium text-gray-500">Agent ID</dt>
                      <dd className="mt-1 text-sm font-mono font-semibold text-primary-600 inline-block select-all break-all">
                        {agent.voice_ai_agent_id}
                      </dd>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-gray-500 italic">No voice AI integration configured.</p>
                )}
              </div>
            </div>
            {!agent.voice_bundle_id &&
              !(agent.voice_ai_integration_id && agent.voice_ai_agent_id) && (
                <p className="text-sm text-gray-500 italic mt-3">No voice configuration detected.</p>
              )}
          </div>
        </div>

        <div className="min-w-0">
          <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
            <h3 className="text-lg font-medium text-gray-900 border-b border-gray-200 pb-2 mb-4">
              System Prompt
            </h3>
            <div>
              {agent.description ? (
                <div className="prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-code:text-gray-800 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-ul:text-gray-700 prose-ol:text-gray-700 max-h-[70vh] overflow-y-auto pr-1">
                  <ReactMarkdown>{agent.description}</ReactMarkdown>
                </div>
              ) : (
                <span className="text-sm text-gray-400">No system prompt configured.</span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
