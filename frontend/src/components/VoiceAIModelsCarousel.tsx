import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ChevronLeft, ChevronRight, ArrowRight } from 'lucide-react'
import { Skeleton } from '@heroui/react'
import { apiClient } from '../lib/api'
import { ModelConfigEntry, ModelProvider } from '../types/api'
import { getProviderDescription, getProviderLabel, getProviderLogo } from '../config/providers'

interface TtsProviderSlide {
  provider: string
  providerLabel: string
  logo: string | null
  description: string
  models: string[]
  featuredModel: string | null
}

function buildTtsProviderSlides(raw: Record<string, ModelConfigEntry>): TtsProviderSlide[] {
  const byProvider = new Map<string, { models: string[]; featuredRank: number; featuredModel: string | null }>()

  for (const [name, config] of Object.entries(raw)) {
    if (config.model_type !== 'tts') continue

    const existing = byProvider.get(config.provider) ?? {
      models: [],
      featuredRank: Number.MAX_SAFE_INTEGER,
      featuredModel: null,
    }

    existing.models.push(name)

    if (config.featured) {
      const rank = config.featured_rank ?? Number.MAX_SAFE_INTEGER
      if (rank < existing.featuredRank) {
        existing.featuredRank = rank
        existing.featuredModel = name
      }
    }

    byProvider.set(config.provider, existing)
  }

  return Array.from(byProvider.entries())
    .map(([provider, data]) => {
      const providerEnum = provider as ModelProvider
      const hasConfig = Object.values(ModelProvider).includes(providerEnum)
      const providerLabel = hasConfig ? getProviderLabel(providerEnum) : provider
      const sortedModels = [...data.models].sort((a, b) => a.localeCompare(b))

      return {
        provider,
        providerLabel,
        logo: hasConfig ? getProviderLogo(providerEnum) : null,
        description: hasConfig
          ? getProviderDescription(providerEnum)
          : `${providerLabel} text-to-speech models`,
        models: sortedModels,
        featuredModel: data.featuredModel ?? sortedModels[0] ?? null,
        sortRank: data.featuredRank,
      }
    })
    .sort((a, b) => {
      if (a.sortRank !== b.sortRank) return a.sortRank - b.sortRank
      return a.providerLabel.localeCompare(b.providerLabel)
    })
    .map(({ sortRank: _, ...slide }) => slide)
}

function buildVoiceBundleLink(provider: string, model: string): string {
  const params = new URLSearchParams({ provider, model })
  return `/voicebundles?${params.toString()}`
}

export default function VoiceAIModelsCarousel() {
  const [currentIndex, setCurrentIndex] = useState(0)
  const [isPaused, setIsPaused] = useState(false)

  const { data: rawModels, isLoading, isError } = useQuery({
    queryKey: ['model-config', 'tts-providers'],
    queryFn: () => apiClient.getAllModels(),
    staleTime: 5 * 60 * 1000,
  })

  const providers = useMemo(() => buildTtsProviderSlides(rawModels || {}), [rawModels])

  const nextSlide = useCallback(() => {
    setCurrentIndex((prev) => (prev + 1) % Math.max(providers.length, 1))
  }, [providers.length])

  const prevSlide = useCallback(() => {
    setCurrentIndex((prev) => (prev - 1 + providers.length) % Math.max(providers.length, 1))
  }, [providers.length])

  const goToSlide = useCallback((index: number) => {
    setCurrentIndex(index)
  }, [])

  useEffect(() => {
    setCurrentIndex(0)
  }, [providers.length])

  useEffect(() => {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReducedMotion || isPaused || providers.length <= 1) return

    const timer = window.setInterval(nextSlide, 6000)
    return () => window.clearInterval(timer)
  }, [isPaused, nextSlide, providers.length])

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-40 w-full rounded-xl" />
        <div className="flex justify-center gap-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-2 w-2 rounded-full" />
          ))}
        </div>
      </div>
    )
  }

  if (isError || providers.length === 0) {
    return (
      <div className="text-center py-10 text-sm text-gray-500">
        {isError ? 'Unable to load TTS providers. Please try again later.' : 'No TTS providers found.'}
      </div>
    )
  }

  return (
    <div
      className="relative w-full"
      onMouseEnter={() => setIsPaused(true)}
      onMouseLeave={() => setIsPaused(false)}
    >
      <div className="overflow-hidden rounded-lg">
        <div
          className="flex transition-transform duration-500 ease-in-out"
          style={{ transform: `translateX(-${currentIndex * 100}%)` }}
        >
          {providers.map((provider) => (
            <div key={provider.provider} className="min-w-full flex-shrink-0">
              <div className="bg-white border border-gray-200 rounded-lg shadow-sm p-6 mx-2">
                <div className="flex items-start gap-4">
                  <div className="w-16 h-16 rounded-lg bg-white border border-gray-200 flex items-center justify-center overflow-hidden flex-shrink-0">
                    {provider.logo ? (
                      <img
                        src={provider.logo}
                        alt={provider.providerLabel}
                        className="w-full h-full object-contain p-2"
                      />
                    ) : (
                      <span className="text-xl font-semibold text-gray-400">
                        {provider.providerLabel.slice(0, 2).toUpperCase()}
                      </span>
                    )}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-2">
                      <h3 className="text-xl font-semibold text-gray-900">{provider.providerLabel}</h3>
                      <span className="px-2.5 py-0.5 bg-gray-100 text-gray-700 rounded-full text-xs font-medium">
                        TTS
                      </span>
                    </div>

                    <p className="text-sm text-gray-600 leading-relaxed mb-3">{provider.description}</p>

                    <p className="text-xs text-gray-500 mb-1">
                      {provider.models.length} model{provider.models.length !== 1 ? 's' : ''} available
                    </p>
                    <p className="text-sm text-gray-700 line-clamp-2">
                      {provider.models.slice(0, 4).join(', ')}
                      {provider.models.length > 4 ? '…' : ''}
                    </p>

                    {provider.featuredModel && (
                      <Link
                        to={buildVoiceBundleLink(provider.provider, provider.featuredModel)}
                        className="inline-flex items-center gap-1 text-sm font-medium text-[#a16207] hover:text-[#854d0e] mt-4"
                      >
                        Use in Voice Bundle
                        <ArrowRight className="w-4 h-4" />
                      </Link>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {providers.length > 1 && (
        <>
          <button
            type="button"
            onClick={prevSlide}
            className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-4 bg-white rounded-full p-2 shadow-lg border border-gray-200 hover:bg-gray-50 transition-colors z-10"
            aria-label="Previous provider"
          >
            <ChevronLeft className="h-5 w-5 text-gray-600" />
          </button>
          <button
            type="button"
            onClick={nextSlide}
            className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-4 bg-white rounded-full p-2 shadow-lg border border-gray-200 hover:bg-gray-50 transition-colors z-10"
            aria-label="Next provider"
          >
            <ChevronRight className="h-5 w-5 text-gray-600" />
          </button>

          <div className="flex justify-center gap-2 mt-4">
            {providers.map((provider, index) => (
              <button
                key={provider.provider}
                type="button"
                onClick={() => goToSlide(index)}
                className={`transition-all duration-300 rounded-full ${
                  index === currentIndex
                    ? 'bg-[#ca8a04] w-8 h-2'
                    : 'bg-gray-300 w-2 h-2 hover:bg-gray-400'
                }`}
                aria-label={`Go to ${provider.providerLabel}`}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
