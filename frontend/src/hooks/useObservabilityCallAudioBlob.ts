import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'

import { apiClient } from '../lib/api'

/** Same-origin blob URL for waveform decode (avoids presigned S3 CORS on fetch). */
export function useObservabilityCallAudioBlob(callShortId: string | undefined, enabled: boolean) {
  const blobUrlRef = useRef<string | null>(null)

  const query = useQuery({
    queryKey: ['observability-call-audio-blob', callShortId],
    queryFn: () => apiClient.getObservabilityCallAudioUrl(callShortId!),
    enabled: !!callShortId && enabled,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  })

  useEffect(() => {
    const nextUrl = query.data
    if (!nextUrl) return
    const prevUrl = blobUrlRef.current
    if (prevUrl && prevUrl !== nextUrl && prevUrl.startsWith('blob:')) {
      URL.revokeObjectURL(prevUrl)
    }
    blobUrlRef.current = nextUrl
  }, [query.data])

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
