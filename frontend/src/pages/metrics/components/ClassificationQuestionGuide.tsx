import { InfoTooltip } from '../../../components/shared'
import {
  CLASSIFICATION_EXAMPLE_STATE,
  CLASSIFICATION_QUESTION_GUIDES,
  type ClassificationQuestionKey,
} from '../classificationQuestionGuides'

export default function ClassificationQuestionGuide({ type }: { type: ClassificationQuestionKey }) {
  const guide = CLASSIFICATION_QUESTION_GUIDES[type]
  return (
    <InfoTooltip
      title={guide.title}
      placement="bottom"
      align="start"
      widthClassName="w-[22rem] max-w-[80vw]"
    >
      <span className="block">{guide.summary}</span>

      <span className="mt-2 block text-[11px] font-semibold uppercase tracking-wide text-gray-400">
        When to use
      </span>
      <span className="mt-0.5 block space-y-0.5">
        {guide.whenToUse.map((item) => (
          <span key={item} className="flex gap-1.5">
            <span className="text-gray-500">•</span>
            <span>{item}</span>
          </span>
        ))}
      </span>

      <span className="mt-2 block text-[11px] font-semibold uppercase tracking-wide text-gray-400">
        Example
      </span>
      <span className="mt-1 block rounded-md bg-gray-800 p-2">
        <span className="block text-[11px] italic text-gray-400">“{CLASSIFICATION_EXAMPLE_STATE}”</span>
        <span className="mt-1.5 block">
          <code className="font-mono text-[11px] text-emerald-300">{guide.example.key}</code>
          <span className="text-gray-300"> — {guide.example.instructions}</span>
        </span>
        <span className="mt-1 block space-y-0.5">
          {guide.example.criteria.map((c) => (
            <span key={c.label} className="flex gap-2">
              <code className="w-16 flex-shrink-0 font-mono text-[11px] text-sky-300">
                {type === 'score' ? `${c.label}.` : c.label}
              </code>
              <span className="text-gray-200">{c.description}</span>
            </span>
          ))}
        </span>
      </span>

      <span className="mt-2 block text-gray-300">
        <span className="font-semibold text-yellow-300">Tip:</span> {guide.tip}
      </span>
    </InfoTooltip>
  )
}
