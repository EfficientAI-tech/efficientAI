import { useQuery } from '@tanstack/react-query'

import { apiClient } from '../lib/api'

/** Fetch a provider-agnostic presigned/signed URL for a blob storage recording key (S3, GCS, or Azure). */
export function useRecordingPresignedUrl(storageKey: string | null | undefined) {
  return useQuery({
    queryKey: ['recording-presigned-url', storageKey],
    queryFn: () => apiClient.getS3PresignedUrl(storageKey!),
    enabled: !!storageKey,
    staleTime: 60 * 1000,
  })
}
