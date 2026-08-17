import { useMemo } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'

import { apiClient } from '../lib/api'
import { useRecordingPresignedUrl } from './useRecordingPresignedUrl'

export type RecordingDownloadTrack = {
  id: string
  label: string
  url: string
}

type CallRecordingKeys = {
  stereo_recording_s3_key?: string | null
  mono_recording_s3_key?: string | null
  user_recording_s3_key?: string | null
  bot_recording_s3_key?: string | null
  recording_s3_key?: string | null
}

const TRACK_DEFINITIONS: Array<{
  id: string
  label: string
  pickKey: (callData: CallRecordingKeys) => string | null | undefined
}> = [
  {
    id: 'stereo',
    label: 'Stereo (dual lane)',
    pickKey: (callData) => callData.stereo_recording_s3_key,
  },
  {
    id: 'mono',
    label: 'Mixed (mono)',
    pickKey: (callData) => callData.mono_recording_s3_key || callData.recording_s3_key,
  },
  {
    id: 'user',
    label: 'User only',
    pickKey: (callData) => callData.user_recording_s3_key,
  },
  {
    id: 'agent',
    label: 'Agent only',
    pickKey: (callData) => callData.bot_recording_s3_key,
  },
]

function buildTrackRequests(callData: CallRecordingKeys | null | undefined) {
  if (!callData) return []

  const seenKeys = new Set<string>()
  return TRACK_DEFINITIONS.flatMap((definition) => {
    const storageKey = definition.pickKey(callData)?.trim()
    if (!storageKey || seenKeys.has(storageKey)) return []
    seenKeys.add(storageKey)
    return [{ id: definition.id, label: definition.label, storageKey }]
  })
}

/** Resolve presigned download URLs for every available call recording artifact. */
export function useRecordingDownloadTracks(callData: CallRecordingKeys | null | undefined) {
  const stereoKey = callData?.stereo_recording_s3_key ?? null
  const monoKey = callData?.mono_recording_s3_key ?? callData?.recording_s3_key ?? null
  const userKey = callData?.user_recording_s3_key ?? null
  const botKey = callData?.bot_recording_s3_key ?? null

  const tracks = useMemo(
    () =>
      buildTrackRequests({
        stereo_recording_s3_key: stereoKey,
        mono_recording_s3_key: monoKey,
        user_recording_s3_key: userKey,
        bot_recording_s3_key: botKey,
        recording_s3_key: callData?.recording_s3_key ?? null,
      }),
    [stereoKey, monoKey, userKey, botKey, callData?.recording_s3_key],
  )

  const queries = useQueries({
    queries: tracks.map((track) => ({
      queryKey: ['recording-presigned-url', track.storageKey],
      queryFn: () => apiClient.getS3PresignedUrl(track.storageKey),
      enabled: !!track.storageKey,
      staleTime: 60 * 1000,
      retry: 1,
    })),
  })

  const resolvedTracks = useMemo(() => {
    const resolved: RecordingDownloadTrack[] = []
    tracks.forEach((track, index) => {
      const url = queries[index]?.data?.url
      if (url) {
        resolved.push({ id: track.id, label: track.label, url })
      }
    })
    return resolved
  }, [tracks, queries])

  const isLoading = tracks.length > 0 && queries.some((query) => query.isLoading)

  return { tracks: resolvedTracks, isLoading }
}

type CallRecordingAudioOptions = {
  callShortId?: string | null
  storageKey?: string | null
  providerRecordingUrl?: string | null
  hasStorageRecording?: boolean
}

/** Resolve playback + waveform URLs, preferring same-origin blob proxies over presigned S3. */
export function useCallRecordingAudioUrls({
  callShortId,
  storageKey,
  providerRecordingUrl,
  hasStorageRecording,
}: CallRecordingAudioOptions) {
  const shouldLoadBlob = Boolean(callShortId && (hasStorageRecording ?? !!storageKey))
  const { data: presignedRecording, isLoading: presignedLoading } = useRecordingPresignedUrl(storageKey)

  const { data: playgroundBlobUrl, isFetching: playgroundLoading } = useQuery({
    queryKey: ['playground-call-audio-url', callShortId],
    queryFn: () => apiClient.getCallRecordingAudioUrl(callShortId!),
    enabled: shouldLoadBlob,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })

  const { data: observabilityBlobUrl, isFetching: observabilityLoading } = useQuery({
    queryKey: ['observability-call-audio-url', callShortId],
    queryFn: () => apiClient.getObservabilityCallAudioUrl(callShortId!),
    enabled: shouldLoadBlob,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })

  const blobUrl = playgroundBlobUrl || observabilityBlobUrl || null
  const playbackUrl = providerRecordingUrl || blobUrl || presignedRecording?.url || null
  const waveformUrl = blobUrl || presignedRecording?.url || playbackUrl

  const isLoading = Boolean(
    !playbackUrl &&
      ((hasStorageRecording ?? !!storageKey) &&
        (presignedLoading || playgroundLoading || observabilityLoading)),
  )

  return {
    playbackUrl,
    waveformUrl,
    blobUrl,
    isLoading,
  }
}

/** @deprecated Use useCallRecordingAudioUrls instead. */
export function useObservabilityRecordingAudioUrl(
  callShortId: string | null | undefined,
  hasStorageRecording: boolean,
  fallbackStorageKey: string | null | undefined,
) {
  return useCallRecordingAudioUrls({
    callShortId,
    storageKey: fallbackStorageKey,
    hasStorageRecording,
  })
}
