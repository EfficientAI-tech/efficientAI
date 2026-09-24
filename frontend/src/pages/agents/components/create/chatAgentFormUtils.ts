import type { TestAgent } from '../../../../types/api'
import type { ChatConnectionConfigForm } from './ChatConnectionDetailsStep'
import type { ChatConnectionForm } from './ChatConnectionStep'

export function chatConnectionFromAgent(agent: TestAgent): ChatConnectionForm {
  const conn = (agent.chat_connection_type || 'internal_llm') as ChatConnectionForm['connectionType']
  return {
    connectionType: conn,
    mainLlmProvider: agent.main_llm_provider || '',
    mainLlmCredentialId: agent.main_llm_credential_id || '',
    mainLlmModel: agent.main_llm_model || '',
    useSeparateTestLlm: Boolean(agent.test_llm_provider && agent.test_llm_model),
    testLlmProvider: agent.test_llm_provider || '',
    testLlmCredentialId: agent.test_llm_credential_id || '',
    testLlmModel: agent.test_llm_model || '',
  }
}

export function chatConfigFromAgent(agent: TestAgent): ChatConnectionConfigForm {
  const cfg = agent.chat_connection_config || {}
  return {
    apiBaseUrl: String(cfg.api_base_url || ''),
    apiMessagePath: String(cfg.api_message_path || '/chat'),
    apiAuthHeader: String(cfg.api_auth_header || 'Authorization'),
    apiAuthValue: String(cfg.api_auth_value || ''),
    messagingChannel: (cfg.messaging_channel as 'whatsapp' | 'sms') || '',
    messagingIntegrationId: String(cfg.messaging_integration_id || ''),
    messagingSenderId: String(cfg.messaging_sender_id || ''),
    outboundWebhookUrl: String(cfg.outbound_webhook_url || cfg.messaging_webhook_url || ''),
    messagingRecipient: String(cfg.messaging_recipient || cfg.messaging_test_recipient || ''),
    messagingSyncReplyUrl: String(cfg.messaging_sync_reply_url || cfg.sync_reply_url || ''),
    metaWhatsappPhoneNumberId: String(cfg.meta_whatsapp_phone_number_id || ''),
    metaWhatsappAccessToken: String(cfg.meta_whatsapp_access_token || ''),
    twilioAccountSid: String(cfg.twilio_account_sid || ''),
    twilioAuthToken: String(cfg.twilio_auth_token || ''),
    twilioFrom: String(cfg.twilio_from || ''),
  }
}

export function buildChatConnectionConfigPayload(
  connectionType: ChatConnectionForm['connectionType'],
  config: ChatConnectionConfigForm,
): Record<string, unknown> | undefined {
  if (connectionType === 'customer_api') {
    return {
      api_base_url: config.apiBaseUrl.trim(),
      api_message_path: config.apiMessagePath.trim() || '/chat',
      ...(config.apiAuthHeader.trim() && config.apiAuthValue.trim()
        ? {
            api_auth_header: config.apiAuthHeader.trim(),
            api_auth_value: config.apiAuthValue.trim(),
          }
        : {}),
    }
  }
  if (connectionType === 'messaging_channels') {
    return {
      messaging_channel: config.messagingChannel,
      ...(config.messagingIntegrationId
        ? { messaging_integration_id: config.messagingIntegrationId }
        : {}),
      ...(config.messagingSenderId.trim()
        ? { messaging_sender_id: config.messagingSenderId.trim() }
        : {}),
      ...(config.outboundWebhookUrl.trim()
        ? { outbound_webhook_url: config.outboundWebhookUrl.trim() }
        : {}),
      ...(config.messagingRecipient.trim()
        ? { messaging_recipient: config.messagingRecipient.trim() }
        : {}),
      ...(config.messagingSyncReplyUrl.trim()
        ? { messaging_sync_reply_url: config.messagingSyncReplyUrl.trim() }
        : {}),
      ...(config.metaWhatsappPhoneNumberId.trim()
        ? { meta_whatsapp_phone_number_id: config.metaWhatsappPhoneNumberId.trim() }
        : {}),
      ...(config.metaWhatsappAccessToken.trim()
        ? { meta_whatsapp_access_token: config.metaWhatsappAccessToken.trim() }
        : {}),
      ...(config.twilioAccountSid.trim()
        ? { twilio_account_sid: config.twilioAccountSid.trim() }
        : {}),
      ...(config.twilioAuthToken.trim()
        ? { twilio_auth_token: config.twilioAuthToken.trim() }
        : {}),
      ...(config.twilioFrom.trim() ? { twilio_from: config.twilioFrom.trim() } : {}),
    }
  }
  return undefined
}

export function chatEvalModeLabel(mode?: string | null): string {
  switch ((mode || 'pre_prod_sim').toLowerCase()) {
    case 'post_prod_live':
      return 'Post-prod live'
    case 'post_prod_import':
      return 'Post-prod import'
    default:
      return 'Pre-prod simulation'
  }
}

export function connectionTypeLabel(type?: string | null): string {
  switch ((type || 'internal_llm').toLowerCase()) {
    case 'provider_chat':
      return 'Voice platform'
    case 'customer_api':
      return 'HTTP API'
    case 'messaging_channels':
      return 'Messaging'
    default:
      return 'Platform LLM'
  }
}
