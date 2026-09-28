import { Bot, Link2, Webhook, MessageCircle } from 'lucide-react'

import type { ChatConnectionType } from './ChatConnectionStep'

import { WizardStepHeader } from './WizardStepHeader'

import {

  CHAT_CONNECTION_CAPABILITIES,

  patternLabel,

  type ChatIntegrationOptionId,

} from '../../../../lib/chatConnectionCapabilities'



export type { ChatIntegrationOptionId }



const ICONS: Record<ChatIntegrationOptionId, typeof Bot> = {

  internal_llm: Bot,

  provider_chat: Link2,

  customer_api: Webhook,

  messaging_channels: MessageCircle,

}



interface ChatIntegrationTypeStepProps {

  value: ChatIntegrationOptionId

  onChange: (value: ChatIntegrationOptionId) => void

  embedded?: boolean

}



export function isChatIntegrationAvailable(id: ChatIntegrationOptionId): boolean {

  return CHAT_CONNECTION_CAPABILITIES.some((c) => c.id === id && c.offeredInCreateWizard)

}



export function chatConnectionTypeFromOption(

  id: ChatIntegrationOptionId,

): ChatConnectionType {

  return id

}



function ConnectionCard({

  id,

  label,

  description,

  pattern,

  selected,

  onSelect,

}: {

  id: ChatIntegrationOptionId

  label: string

  description: string

  pattern: 'llm_to_llm' | 'live_production_plus_customer_llm'

  selected: boolean

  onSelect: () => void

}) {

  const Icon = ICONS[id]

  const badge =

    pattern === 'llm_to_llm'

      ? 'LLM-to-LLM'

      : 'Live production'



  return (

    <button

      type="button"

      onClick={onSelect}

      className={`text-left rounded-xl border-2 p-4 transition-colors ${

        selected ? 'border-primary-600 bg-primary-50' : 'border-gray-200 bg-white hover:border-gray-300'

      }`}

    >

      <div className="flex items-start gap-3">

        <div

          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${

            selected ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600'

          }`}

        >

          <Icon className="h-5 w-5" />

        </div>

        <div className="min-w-0 flex-1">

          <div className="flex flex-wrap items-center gap-2">

            <span className="text-sm font-semibold text-gray-900">{label}</span>

            <span

              className={`text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded ${

                pattern === 'llm_to_llm'

                  ? 'bg-violet-100 text-violet-800'

                  : 'bg-slate-100 text-slate-700'

              }`}

            >

              {badge}

            </span>

          </div>

          <span className="text-xs text-gray-600 mt-1 block leading-relaxed">{description}</span>

        </div>

      </div>

    </button>

  )

}



export default function ChatIntegrationTypeStep({

  value,

  onChange,

  embedded,

}: ChatIntegrationTypeStepProps) {

  const llmToLlm = CHAT_CONNECTION_CAPABILITIES.filter((c) => c.pattern === 'llm_to_llm')

  const live = CHAT_CONNECTION_CAPABILITIES.filter((c) => c.pattern === 'live_production_plus_customer_llm')



  return (

    <div className={embedded ? 'w-full space-y-4' : 'w-full max-w-3xl mx-auto space-y-6'}>

      {!embedded ? (

        <WizardStepHeader

          title="How does production chat connect?"

          subtitle="Only Platform LLM is full LLM-to-LLM. Other options call your live stack each turn; the test agent side stays an LLM."

        />

      ) : null}



      <section className="space-y-2">

        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">

          {patternLabel('llm_to_llm')}

        </h4>

        <div className="grid grid-cols-1 gap-3">

          {llmToLlm.map((option) => (

            <ConnectionCard

              key={option.id}

              id={option.id}

              label={option.label}

              description={option.description}

              pattern={option.pattern}

              selected={value === option.id}

              onSelect={() => onChange(option.id)}

            />

          ))}

        </div>

      </section>



      <section className="space-y-2">

        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">

          {patternLabel('live_production_plus_customer_llm')}

        </h4>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">

          {live.map((option) => (

            <ConnectionCard

              key={option.id}

              id={option.id}

              label={option.label}

              description={option.description}

              pattern={option.pattern}

              selected={value === option.id}

              onSelect={() => onChange(option.id)}

            />

          ))}

        </div>

        <p className="text-xs text-gray-500">

          Provider live chat uses native text APIs on Vapi, Retell, ElevenLabs, and Smallest only.

        </p>

      </section>

    </div>

  )

}


