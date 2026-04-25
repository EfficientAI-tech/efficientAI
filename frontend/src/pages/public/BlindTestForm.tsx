import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle2,
  Headphones,
  Loader2,
  Pause,
  Play,
} from 'lucide-react'
import { publicBlindTestApi, PublicBlindTestEntrySubmit } from '../../lib/api'
import { BlindTestCustomMetric, PublicBlindTestForm } from '../playground/voice/types'

interface SampleAnswer {
  preferred?: 'X' | 'Y'
  ratings_x: Record<string, number>
  ratings_y: Record<string, number>
  comment?: string
}

function buildEmptyAnswer(): SampleAnswer {
  return { ratings_x: {}, ratings_y: {} }
}

function StarRating({
  scale,
  value,
  onChange,
}: {
  scale: number
  value: number | undefined
  onChange: (v: number) => void
}) {
  return (
    <div className="flex items-center gap-1">
      {Array.from({ length: scale }).map((_, idx) => {
        const v = idx + 1
        const filled = value !== undefined && v <= value
        return (
          <button
            key={v}
            type="button"
            onClick={() => onChange(v)}
            className={`w-7 h-7 flex items-center justify-center rounded text-sm font-semibold border transition ${
              filled
                ? 'bg-amber-400 border-amber-500 text-white'
                : 'bg-white border-gray-300 text-gray-400 hover:border-amber-400'
            }`}
            aria-label={`Rate ${v}`}
          >
            {v}
          </button>
        )
      })}
    </div>
  )
}

function AudioPlayer({
  url,
  label,
  selected,
  onSelect,
}: {
  url: string | null
  label: string
  selected: boolean
  onSelect: () => void
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [playing, setPlaying] = useState(false)

  useEffect(() => {
    return () => {
      audioRef.current?.pause()
      audioRef.current = null
    }
  }, [])

  const toggle = () => {
    if (!url) return
    if (!audioRef.current) {
      audioRef.current = new Audio(url)
      audioRef.current.onended = () => setPlaying(false)
    }
    if (playing) {
      audioRef.current.pause()
      setPlaying(false)
    } else {
      audioRef.current.currentTime = 0
      audioRef.current.play()
      setPlaying(true)
    }
  }

  return (
    <div
      className={`flex flex-col items-center gap-2 p-4 rounded-xl border-2 transition cursor-pointer ${
        selected
          ? 'border-amber-500 bg-amber-50'
          : 'border-gray-200 bg-white hover:border-amber-300'
      }`}
      onClick={onSelect}
    >
      <p className="text-sm font-semibold text-gray-700">{label}</p>
      <button
        type="button"
        onClick={e => {
          e.stopPropagation()
          toggle()
        }}
        className="w-12 h-12 rounded-full bg-amber-400 hover:bg-amber-500 text-white flex items-center justify-center disabled:opacity-50"
        disabled={!url}
      >
        {playing ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5 ml-0.5" />}
      </button>
      <p className="text-xs text-gray-500">
        {selected ? 'Selected as your preferred' : 'Click to choose'}
      </p>
    </div>
  )
}

export default function BlindTestForm() {
  const { token } = useParams<{ token: string }>()

  const { data, isLoading, isError, error } = useQuery<PublicBlindTestForm>({
    queryKey: ['public-blind-test', token],
    queryFn: () => publicBlindTestApi.getForm(token!),
    enabled: !!token,
    retry: false,
  })

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [answers, setAnswers] = useState<Record<number, SampleAnswer>>({})
  const [submitted, setSubmitted] = useState(false)

  useEffect(() => {
    if (data?.samples) {
      const init: Record<number, SampleAnswer> = {}
      for (const s of data.samples) init[s.sample_index] = buildEmptyAnswer()
      setAnswers(init)
    }
  }, [data?.samples])

  const ratingMetrics = useMemo<BlindTestCustomMetric[]>(
    () => (data?.custom_metrics || []).filter(m => m.type === 'rating'),
    [data?.custom_metrics]
  )
  const commentMetric = useMemo(
    () => (data?.custom_metrics || []).find(m => m.type === 'comment'),
    [data?.custom_metrics]
  )

  const submitMutation = useMutation({
    mutationFn: async () => {
      if (!data || !token) return
      const payload = {
        rater_name: name.trim(),
        rater_email: email.trim(),
        client_token: data.client_token,
        responses: data.samples.map<PublicBlindTestEntrySubmit>(s => {
          const ans = answers[s.sample_index] || buildEmptyAnswer()
          return {
            sample_index: s.sample_index,
            preferred: ans.preferred || 'X',
            ratings_x: ans.ratings_x,
            ratings_y: ans.ratings_y,
            ...(ans.comment ? { comment: ans.comment } : {}),
          }
        }),
      }
      return publicBlindTestApi.submit(token, payload)
    },
    onSuccess: () => setSubmitted(true),
  })

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
      </div>
    )
  }

  if (isError) {
    const status = (error as any)?.response?.status
    const message =
      (error as any)?.response?.data?.detail ||
      (status === 404
        ? 'This blind test link is not valid.'
        : status === 410
          ? 'This blind test is no longer accepting responses.'
          : 'Could not load this blind test.')
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 p-6">
        <div className="max-w-md w-full bg-white rounded-xl shadow-lg p-8 text-center space-y-3">
          <AlertCircle className="w-10 h-10 mx-auto text-amber-500" />
          <h1 className="text-xl font-semibold text-gray-900">Unavailable</h1>
          <p className="text-sm text-gray-600">{String(message)}</p>
        </div>
      </div>
    )
  }

  if (!data) return null

  if (submitted) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 p-6">
        <div className="max-w-md w-full bg-white rounded-xl shadow-lg p-8 text-center space-y-3">
          <CheckCircle2 className="w-10 h-10 mx-auto text-green-500" />
          <h1 className="text-xl font-semibold text-gray-900">Thanks for your response!</h1>
          <p className="text-sm text-gray-600">
            Your ratings have been recorded. You can close this tab now.
          </p>
        </div>
      </div>
    )
  }

  const submitErrorStatus = (submitMutation.error as any)?.response?.status
  const alreadySubmitted = submitErrorStatus === 409

  if (alreadySubmitted) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 p-6">
        <div className="max-w-md w-full bg-white rounded-xl shadow-lg p-8 text-center space-y-3">
          <CheckCircle2 className="w-10 h-10 mx-auto text-amber-500" />
          <h1 className="text-xl font-semibold text-gray-900">You&apos;ve already responded</h1>
          <p className="text-sm text-gray-600">
            We&rsquo;ve recorded an earlier submission from <span className="font-medium">{email.trim()}</span> for this blind test.
            Only one response per email is accepted.
          </p>
        </div>
      </div>
    )
  }

  const allSamplesAnswered = data.samples.every(
    s => !!answers[s.sample_index]?.preferred
  )
  const formValid = name.trim() && /\S+@\S+\.\S+/.test(email.trim()) && allSamplesAnswered
  const submitError = submitMutation.error
    ? (submitMutation.error as any)?.response?.data?.detail ||
      (submitMutation.error as any)?.message
    : null

  return (
    <div className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-3xl mx-auto space-y-6">
        <header className="bg-white rounded-xl shadow-lg p-6">
          <div className="flex items-center gap-3 mb-2">
            <Headphones className="w-6 h-6 text-amber-500" />
            <h1 className="text-2xl font-bold text-gray-900">{data.title}</h1>
          </div>
          {data.description && (
            <p className="text-sm text-gray-600 whitespace-pre-line">{data.description}</p>
          )}
        </header>

        <section className="bg-white rounded-xl shadow-lg p-6">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Tell us who you are</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Your name *"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
            />
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="Your email *"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
            />
          </div>
        </section>

        {data.samples.map((sample, idx) => {
          const ans = answers[sample.sample_index] || buildEmptyAnswer()
          const setAns = (patch: Partial<SampleAnswer>) =>
            setAnswers(prev => ({
              ...prev,
              [sample.sample_index]: { ...buildEmptyAnswer(), ...prev[sample.sample_index], ...patch },
            }))

          return (
            <section
              key={sample.sample_index}
              className="bg-white rounded-xl shadow-lg p-6 space-y-5"
            >
              <div>
                <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">
                  Sample {idx + 1} of {data.samples.length}
                </p>
                <p className="text-base text-gray-800 italic">“{sample.text}”</p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <AudioPlayer
                  url={sample.voice_x_url}
                  label="Voice X"
                  selected={ans.preferred === 'X'}
                  onSelect={() => setAns({ preferred: 'X' })}
                />
                <AudioPlayer
                  url={sample.voice_y_url}
                  label="Voice Y"
                  selected={ans.preferred === 'Y'}
                  onSelect={() => setAns({ preferred: 'Y' })}
                />
              </div>

              {ratingMetrics.length > 0 && (
                <div className="space-y-3">
                  <p className="text-sm font-semibold text-gray-700">Rate each voice</p>
                  {ratingMetrics.map(m => (
                    <div key={m.key} className="grid grid-cols-1 md:grid-cols-3 gap-3 items-center">
                      <span className="text-sm text-gray-700">{m.label}</span>
                      <div>
                        <p className="text-xs text-gray-500 mb-1">Voice X</p>
                        <StarRating
                          scale={m.scale || 5}
                          value={ans.ratings_x[m.key]}
                          onChange={v =>
                            setAns({
                              ratings_x: { ...ans.ratings_x, [m.key]: v },
                            })
                          }
                        />
                      </div>
                      <div>
                        <p className="text-xs text-gray-500 mb-1">Voice Y</p>
                        <StarRating
                          scale={m.scale || 5}
                          value={ans.ratings_y[m.key]}
                          onChange={v =>
                            setAns({
                              ratings_y: { ...ans.ratings_y, [m.key]: v },
                            })
                          }
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {commentMetric && (
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-1">
                    {commentMetric.label} <span className="text-gray-400 font-normal">(optional)</span>
                  </label>
                  <textarea
                    rows={2}
                    value={ans.comment || ''}
                    onChange={e => setAns({ comment: e.target.value })}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
                    placeholder="Anything stand out about either voice?"
                  />
                </div>
              )}
            </section>
          )
        })}

        <section className="bg-white rounded-xl shadow-lg p-6 flex flex-col gap-3">
          {submitError && (
            <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
              {String(submitError)}
            </div>
          )}
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-gray-500">
              {!allSamplesAnswered &&
                'Pick a preferred voice for every sample to enable submit.'}
            </p>
            <button
              type="button"
              onClick={() => submitMutation.mutate()}
              disabled={!formValid || submitMutation.isPending}
              className={`px-5 py-2 rounded-full text-sm font-semibold transition ${
                formValid && !submitMutation.isPending
                  ? 'bg-amber-500 hover:bg-amber-600 text-white'
                  : 'bg-gray-200 text-gray-400 cursor-not-allowed'
              }`}
            >
              {submitMutation.isPending ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Submitting...
                </span>
              ) : (
                'Submit response'
              )}
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}
