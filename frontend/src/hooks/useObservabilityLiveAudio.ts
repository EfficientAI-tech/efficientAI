import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'

import { apiClient } from '../lib/api'

export interface LiveAudioSnapshot {
  blobUrl: string
  durationSec: number
}

/** Poll partial live call audio (merged mono WAV) while the call is in progress. */
export function useObservabilityLiveAudio(callShortId: string | undefined, enabled: boolean) {
  const blobUrlRef = useRef<string | null>(null)

  const query = useQuery({
    queryKey: ['observability-live-audio', callShortId],
    queryFn: async (): Promise<LiveAudioSnapshot> => {
      const { blob, durationSec } = await apiClient.getObservabilityLiveAudioBlob(callShortId!)
      const blobUrl = URL.createObjectURL(blob)
      return { blobUrl, durationSec }
    },
    enabled: !!callShortId && enabled,
    refetchInterval: enabled ? 3000 : false,
    staleTime: 0,
    retry: (failureCount, error) => {
      if (failureCount >= 2) return false
      const status = (error as { response?: { status?: number } })?.response?.status
      return status !== 404
    },
  })

  useEffect(() => {
    const nextUrl = query.data?.blobUrl
    if (!nextUrl) return
    const prevUrl = blobUrlRef.current
    if (prevUrl && prevUrl !== nextUrl && prevUrl.startsWith('blob:')) {
      URL.revokeObjectURL(prevUrl)
    }
    blobUrlRef.current = nextUrl
  }, [query.data?.blobUrl])

  useEffect(() => {
    return () => {
      const url = blobUrlRef.current
      if (url?.startsWith('blob:')) {
        URL.revokeObjectURL(url)
      }
      blobUrlRef.current = null
    }
  }, [callShortId])

  return query
}
