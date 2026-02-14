/**
 * Centralized provider configuration
 * Single source of truth for all provider metadata in the frontend
 */

import { ModelProvider, IntegrationPlatform } from '../types/api'

export interface ProviderMetadata {
  label: string
  logo: string | null
  description: string
}

export const MODEL_PROVIDER_CONFIG: Record<ModelProvider, ProviderMetadata> = {
  [ModelProvider.OPENAI]: {
    label: 'OpenAI',
    logo: '/openai-logo.png',
    description: 'GPT models, Whisper, TTS',
  },
  [ModelProvider.ANTHROPIC]: {
    label: 'Anthropic',
    logo: '/anthropic.png',
    description: 'Claude models',
  },
  [ModelProvider.GOOGLE]: {
    label: 'Google',
    logo: '/geminiai.png',
    description: 'Gemini, Google Speech, Google TTS',
  },
  [ModelProvider.AZURE]: {
    label: 'Azure',
    logo: '/azureai.png',
    description: 'Azure OpenAI, Azure Speech Services',
  },
  [ModelProvider.AWS]: {
    label: 'AWS',
    logo: '/AWS_logo.png',
    description: 'AWS Bedrock, Transcribe, Polly',
  },
  [ModelProvider.DEEPGRAM]: {
    label: 'Deepgram',
    logo: '/deepgram.png',
    description: 'Deepgram STT',
  },
  [ModelProvider.CARTESIA]: {
    label: 'Cartesia',
    logo: '/cartesia.jpg',
    description: 'Cartesia TTS',
  },
  [ModelProvider.ELEVENLABS]: {
    label: 'ElevenLabs',
    logo: '/elevenlabs.jpg',
    description: 'ElevenLabs TTS',
  },
  [ModelProvider.CUSTOM]: {
    label: 'Custom',
    logo: null,
    description: 'Custom AI provider',
  },
}

export interface IntegrationPlatformMetadata {
  label: string
  logo: string | null
  description: string
  // Maps to ModelProvider for use in VoiceBundles (if applicable)
  modelProvider: ModelProvider | null
}

export const INTEGRATION_PLATFORM_CONFIG: Record<IntegrationPlatform, IntegrationPlatformMetadata> = {
  [IntegrationPlatform.RETELL]: {
    label: 'Retell AI',
    logo: '/retellai.png',
    description: 'Connect your Retell AI voice agents',
    modelProvider: null, // Voice AI platform, not a model provider
  },
  [IntegrationPlatform.VAPI]: {
    label: 'Vapi',
    logo: '/vapiai.jpg',
    description: 'Connect your Vapi voice AI agents',
    modelProvider: null, // Voice AI platform, not a model provider
  },
  [IntegrationPlatform.CARTESIA]: {
    label: 'Cartesia',
    logo: '/cartesia.jpg',
    description: 'Cartesia TTS for voice synthesis',
    modelProvider: ModelProvider.CARTESIA,
  },
  [IntegrationPlatform.ELEVENLABS]: {
    label: 'ElevenLabs',
    logo: '/elevenlabs.jpg',
    description: 'ElevenLabs TTS for voice synthesis',
    modelProvider: ModelProvider.ELEVENLABS,
  },
  [IntegrationPlatform.DEEPGRAM]: {
    label: 'Deepgram',
    logo: '/deepgram.png',
    description: 'Deepgram STT for speech recognition',
    modelProvider: ModelProvider.DEEPGRAM,
  },
}

// Helper functions
export const getProviderLabel = (provider: ModelProvider): string => 
  MODEL_PROVIDER_CONFIG[provider]?.label ?? provider

export const getProviderLogo = (provider: ModelProvider): string | null => 
  MODEL_PROVIDER_CONFIG[provider]?.logo ?? null

export const getProviderDescription = (provider: ModelProvider): string => 
  MODEL_PROVIDER_CONFIG[provider]?.description ?? ''

export const getIntegrationPlatformLabel = (platform: IntegrationPlatform): string => 
  INTEGRATION_PLATFORM_CONFIG[platform]?.label ?? platform

export const getIntegrationPlatformLogo = (platform: IntegrationPlatform): string | null => 
  INTEGRATION_PLATFORM_CONFIG[platform]?.logo ?? null

export const mapIntegrationToModelProvider = (platform: IntegrationPlatform): ModelProvider | null => 
  INTEGRATION_PLATFORM_CONFIG[platform]?.modelProvider ?? null
