import { useState } from 'react'
import { Check, Pencil, X } from 'lucide-react'

import PromptLineDiff, { PromptDiffViewToggle, type PromptDiffView } from './PromptLineDiff'
import type { PromptImprovementSuggestion } from '../../../types/api'

const GAP_LABEL_STYLES: Record<string, string> = {
  LOGIC_GAP: 'bg-rose-50 text-rose-700 border-rose-200',
  UNDERSPEC: 'bg-amber-50 text-amber-700 border-amber-200',
  EXISTS_NO_TRIGGER: 'bg-sky-50 text-sky-700 border-sky-200',
  MISSING: 'bg-violet-50 text-violet-700 border-violet-200',
}

const PRIORITY_STYLES: Record<string, string> = {
  high: 'text-rose-700',
  medium: 'text-amber-700',
  low: 'text-gray-600',
}

const CHANGE_TYPE_STYLES: Record<string, string> = {
  edit: 'bg-blue-50 text-blue-700 border-blue-200',
  add: 'bg-emerald-50 text-emerald-700 border-emerald-200',
}

export type PromptSuggestionReview = {
  suggestion_id: string
  review_status: 'pending' | 'accepted' | 'rejected'
  edited_text?: string | null
}

/** Suggestion cards with diff, accept / reject / edit; shared by call imports and simulations. */
export default function PromptSuggestionList({
  suggestions,
  onReview,
  isReviewing,
  diffView,
  onDiffViewChange,
  activeSuggestionId = null,
  onFocus,
  acceptedNote,
  appliedNote,
}: {
  suggestions: PromptImprovementSuggestion[]
  onReview: (data: PromptSuggestionReview) => Promise<unknown>
  isReviewing: boolean
  diffView: PromptDiffView
  onDiffViewChange: (view: PromptDiffView) => void
  activeSuggestionId?: string | null
  onFocus?: (suggestion: PromptImprovementSuggestion) => void
  acceptedNote: string
  appliedNote: string
}) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftText, setDraftText] = useState('')

  const review = (data: PromptSuggestionReview) => {
    onReview(data)
      .then(() => setEditingId(null))
      .catch(() => undefined)
  }

  return (
    <div className="space-y-3 min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-gray-200 bg-gray-50 px-3 py-2">
        <span className="text-xs font-medium text-gray-600">Suggestion diffs</span>
        <PromptDiffViewToggle view={diffView} onChange={onDiffViewChange} />
      </div>
      {suggestions.map((suggestion, index) => {
        const isActive = activeSuggestionId === suggestion.id
        const changeType = suggestion.change_type || 'add'
        const changeLabel = changeType === 'edit' ? 'Edit existing' : 'New addition'
        const reviewStatus = suggestion.review_status || 'pending'
        const isAccepted = reviewStatus === 'accepted'
        const isRejected = reviewStatus === 'rejected'
        const isApplied = reviewStatus === 'applied'
        const isPending = reviewStatus === 'pending' || reviewStatus === undefined

        const cardSurfaceClass = isApplied
          ? 'border-sky-300 bg-sky-50/50 ring-1 ring-sky-200/80'
          : isAccepted
          ? 'border-emerald-300 bg-emerald-50/50 ring-1 ring-emerald-200/80'
          : isRejected
            ? 'border-rose-200 bg-rose-50/35 ring-1 ring-rose-100'
            : isActive
              ? 'border-primary-300 bg-primary-50/30'
              : 'border-gray-200 bg-gray-50/60'

        return (
          <article
            key={suggestion.id}
            className={`rounded-md border p-3 space-y-2 min-w-0 overflow-hidden transition-all duration-200 ${cardSurfaceClass}`}
          >
            <div className="flex flex-wrap items-center gap-2 min-w-0">
              <button
                type="button"
                onClick={() => onFocus?.(suggestion)}
                className="text-sm font-semibold text-gray-900 break-words min-w-0 flex-1 text-left hover:text-primary-700"
              >
                {index + 1}. {suggestion.metric_name} · {suggestion.cluster_label}
              </button>
              <span
                className={`text-[10px] uppercase tracking-wide font-semibold rounded border px-1.5 py-0.5 ${
                  CHANGE_TYPE_STYLES[changeType] || 'bg-gray-100 text-gray-700 border-gray-200'
                }`}
              >
                {changeLabel}
              </span>
              <span
                className={`text-[10px] uppercase tracking-wide font-semibold rounded border px-1.5 py-0.5 ${
                  GAP_LABEL_STYLES[suggestion.gap_label] || 'bg-gray-100 text-gray-700 border-gray-200'
                }`}
              >
                {suggestion.gap_label}
              </span>
              <span
                className={`text-xs font-medium ${
                  PRIORITY_STYLES[suggestion.priority] || 'text-gray-600'
                }`}
              >
                {suggestion.priority} priority
              </span>
              <span className="text-xs text-gray-500 tabular-nums">
                {suggestion.share_pct.toFixed(1)}% cluster share
              </span>
            </div>

            {suggestion.target_section ? (
              <p className="text-xs text-gray-600 break-words">
                <span className="font-medium">Target section:</span>{' '}
                {suggestion.target_section}
              </p>
            ) : null}

            {suggestion.flow_node_label ? (
              <p className="text-xs text-gray-600 break-words">
                <span className="font-medium">Agent logic node:</span>{' '}
                <button
                  type="button"
                  onClick={() => onFocus?.(suggestion)}
                  className="text-primary-700 hover:text-primary-800 underline-offset-2 hover:underline"
                >
                  {suggestion.flow_node_label}
                </button>
              </p>
            ) : null}

            {suggestion.current_gap ? (
              <p className="text-xs text-gray-600 break-words">
                <span className="font-medium">Current gap:</span> {suggestion.current_gap}
              </p>
            ) : null}

            {suggestion.rationale ? (
              <p className="text-xs text-gray-500 break-words">{suggestion.rationale}</p>
            ) : null}

            <PromptLineDiff
              view={diffView}
              leftLabel={changeType === 'edit' ? 'Current excerpt' : '—'}
              rightLabel={changeType === 'edit' ? 'Suggested text' : 'New section'}
              before={changeType === 'edit' ? suggestion.anchor_excerpt || '' : ''}
              after={
                suggestion.edited_text?.trim()
                  ? suggestion.edited_text
                  : suggestion.suggested_text
              }
              maxHeightClass="max-h-64"
            />

            {editingId === suggestion.id ? (
              <div className="space-y-2">
                <textarea
                  value={draftText}
                  onChange={(event) => setDraftText(event.target.value)}
                  rows={6}
                  className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono text-gray-800"
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={isReviewing || !draftText.trim()}
                    onClick={() =>
                      review({
                        suggestion_id: suggestion.id,
                        review_status: 'accepted',
                        edited_text: draftText,
                      })
                    }
                    className="rounded border border-emerald-300 bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-800 disabled:opacity-50"
                  >
                    Accept edited text
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditingId(null)}
                    className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                {isApplied ? (
                  <p className="inline-flex items-center gap-1.5 rounded-md border border-sky-300 bg-sky-100 px-2.5 py-1.5 text-xs font-medium text-sky-900">
                    <Check className="h-3.5 w-3.5 shrink-0" />
                    {appliedNote}
                  </p>
                ) : null}
                {isAccepted ? (
                  <p className="inline-flex items-center gap-1.5 rounded-md border border-emerald-300 bg-emerald-100 px-2.5 py-1.5 text-xs font-medium text-emerald-900">
                    <Check className="h-3.5 w-3.5 shrink-0" />
                    {acceptedNote}
                  </p>
                ) : null}
                {isRejected ? (
                  <p className="inline-flex items-center gap-1.5 rounded-md border border-rose-200 bg-rose-100/80 px-2.5 py-1.5 text-xs font-medium text-rose-900">
                    <X className="h-3.5 w-3.5 shrink-0" />
                    Rejected — excluded from the composed prompt
                  </p>
                ) : null}
                <div className="flex flex-wrap items-center gap-2">
                  {isPending ? (
                    <span
                      className="text-[10px] uppercase tracking-wide font-semibold rounded border px-1.5 py-0.5 bg-gray-100 text-gray-600 border-gray-200"
                    >
                      pending
                    </span>
                  ) : null}
                  <button
                    type="button"
                    disabled={isReviewing || isAccepted || isApplied}
                    onClick={() =>
                      review({
                        suggestion_id: suggestion.id,
                        review_status: 'accepted',
                      })
                    }
                    className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition ${
                      isAccepted
                        ? 'border border-emerald-500 bg-emerald-600 text-white cursor-default shadow-sm'
                        : 'border border-emerald-300 bg-white text-emerald-800 hover:bg-emerald-50'
                    }`}
                  >
                    <Check className="h-3 w-3" />
                    {isAccepted ? 'Accepted' : 'Accept this change'}
                  </button>
                  <button
                    type="button"
                    disabled={isReviewing || isRejected || isApplied}
                    onClick={() =>
                      review({
                        suggestion_id: suggestion.id,
                        review_status: 'rejected',
                      })
                    }
                    className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition ${
                      isRejected
                        ? 'border border-rose-400 bg-rose-600 text-white cursor-default shadow-sm'
                        : 'border border-rose-300 bg-white text-rose-800 hover:bg-rose-50'
                    }`}
                  >
                    <X className="h-3 w-3" />
                    {isRejected ? 'Rejected' : 'Reject this change'}
                  </button>
                  {!isRejected ? (
                    <button
                      type="button"
                      onClick={() => {
                        setEditingId(suggestion.id)
                        setDraftText(
                          suggestion.edited_text?.trim()
                            ? suggestion.edited_text
                            : suggestion.suggested_text,
                        )
                      }}
                      className="inline-flex items-center gap-1 rounded border border-gray-300 bg-white px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                    >
                      <Pencil className="h-3 w-3" />
                      Edit manually
                    </button>
                  ) : null}
                </div>
              </div>
            )}
          </article>
        )
      })}
    </div>
  )
}
