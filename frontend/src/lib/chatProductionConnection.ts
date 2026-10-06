import {
  getIntegrationPlatformLabel,
  getIntegrationPlatformLogo,
} from '../config/providers'
import {
  Integration,
  IntegrationPlatform,
  TelephonyProvider,
  TestAgent,
} from '../types/api'
import type { TelephonyIntegrationResponse, TelephonyPhoneNumberResponse } from './api'
import { messagingChannelFromConfig, smsCarrierFromTelephony } from './messagingEvalUi'

export type ChatProductionConnectionDisplay = {
  headline: string
  detail?: string
  telephonyProvider?: TelephonyProvider | null
  platformLogo?: string | null
}

function connectionKindLabel(type?: string | null): string {
  switch ((type || 'internal_llm').toLowerCase()) {
    case 'provider_chat':
      return 'Existing platform'
    case 'customer_api':
      return 'HTTP API'
    case 'customer_websocket':
      return 'WebSocket'
    case 'messaging_channels':
      return 'Messaging'
    default:
      return 'LLM'
  }
}

export function resolveChatProductionConnectionDisplay(args: {
  chatConnectionType?: string | null
  chatConnectionConfig?: Record<string, unknown> | null
  telephonyPhoneNumberId?: string | null
  telephonyConfigs?: TelephonyIntegrationResponse[]
  telephonyNumbers?: TelephonyPhoneNumberResponse[]
  voiceIntegration?: Integration | null
  mainLlmModel?: string | null
}): ChatProductionConnectionDisplay {
  const conn = (args.chatConnectionType || 'internal_llm').toLowerCase()
  const cfg = args.chatConnectionConfig || {}

  if (conn === 'messaging_channels') {
    const channel = messagingChannelFromConfig(cfg)
    const integrationId = String(
      cfg.messaging_telephony_integration_id || cfg.messaging_integration_id || '',
    ).trim()
    const telephonyCfg = args.telephonyConfigs?.find((c) => c.id === integrationId)
    const integrationName = telephonyCfg?.name?.trim()

    if (channel === 'whatsapp') {
      const sender = String(
        cfg.meta_whatsapp_phone_number_id || cfg.messaging_sender_id || '',
      ).trim()
      const detailParts = [integrationName, sender ? `Phone number ID ${sender}` : ''].filter(
        Boolean,
      )
      return {
        headline: 'WhatsApp (Meta)',
        detail: detailParts.join(' · ') || undefined,
        telephonyProvider: TelephonyProvider.META_WHATSAPP,
      }
    }

    const carrier = smsCarrierFromTelephony(
      args.telephonyPhoneNumberId,
      args.telephonyNumbers || [],
    )
    const numberRow = args.telephonyNumbers?.find((n) => n.id === args.telephonyPhoneNumberId)
    const carrierLabel =
      carrier === 'telnyx' ? 'Telnyx SMS' : carrier === 'twilio' ? 'Twilio SMS' : 'SMS'
    const detailParts = [integrationName, numberRow?.phone_number].filter(Boolean)
    return {
      headline: carrierLabel,
      detail: detailParts.join(' · ') || undefined,
      telephonyProvider:
        carrier === 'telnyx'
          ? TelephonyProvider.TELNYX
          : carrier === 'twilio'
            ? TelephonyProvider.TWILIO
            : null,
    }
  }

  if (conn === 'provider_chat' && args.voiceIntegration) {
    const platform = args.voiceIntegration.platform as IntegrationPlatform
    return {
      headline: getIntegrationPlatformLabel(platform),
      detail: args.voiceIntegration.name?.trim() || undefined,
      platformLogo: getIntegrationPlatformLogo(platform),
    }
  }

  if (conn === 'internal_llm') {
    const model = args.mainLlmModel?.trim()
    return {
      headline: 'LLM simulation',
      detail: model || undefined,
    }
  }

  if (conn === 'customer_api') {
    const base = String(cfg.api_base_url || '').trim()
    return { headline: 'HTTP API', detail: base || undefined }
  }

  if (conn === 'customer_websocket') {
    const url = String(cfg.websocket_url || '').trim()
    return { headline: 'WebSocket', detail: url || undefined }
  }

  return { headline: connectionKindLabel(args.chatConnectionType) }
}

export function resolveChatProductionConnectionFromAgent(
  agent: TestAgent,
  ctx: {
    telephonyConfigs?: TelephonyIntegrationResponse[]
    telephonyNumbers?: TelephonyPhoneNumberResponse[]
    voiceIntegration?: Integration | null
  },
): ChatProductionConnectionDisplay {
  return resolveChatProductionConnectionDisplay({
    chatConnectionType: agent.chat_connection_type,
    chatConnectionConfig: agent.chat_connection_config,
    telephonyPhoneNumberId: agent.telephony_phone_number_id,
    telephonyConfigs: ctx.telephonyConfigs,
    telephonyNumbers: ctx.telephonyNumbers,
    voiceIntegration: ctx.voiceIntegration,
    mainLlmModel: agent.main_llm_model,
  })
}
