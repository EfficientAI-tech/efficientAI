export type ClassificationQuestionKey = 'noul' | 'choice' | 'score'

export type ClassificationQuestionGuide = {
  title: string
  summary: string
  whenToUse: string[]
  example: {
    key: string
    instructions: string
    /** Rendered as `label → description` rows (choice/noul) or numbered levels (score). */
    criteria: { label: string; description: string }[]
  }
  tip: string
}

/**
 * Help content for each System 1 (Jev) question type. Examples follow a single
 * support-ticket scenario so the three types read as one coherent metric.
 */
export const CLASSIFICATION_EXAMPLE_STATE =
  "Hi, I've been trying to connect my Stripe account for 3 days and the integration keeps failing. I'm losing sales. Please help ASAP."

export const CLASSIFICATION_QUESTION_GUIDES: Record<ClassificationQuestionKey, ClassificationQuestionGuide> = {
  noul: {
    title: 'Noul · yes / no',
    summary: 'Returns the probability that a statement is true for the conversation.',
    whenToUse: [
      'A single binary check — resolved?, escalated?, urgent?',
      'You want a confidence (0–1), not just a label',
    ],
    example: {
      key: 'is_urgent',
      instructions: 'The message conveys urgency or time-sensitivity',
      criteria: [
        { label: 'true', description: 'Customer signals a deadline, lost revenue, or asks for ASAP help' },
        { label: 'false', description: 'No time pressure is expressed' },
      ],
    },
    tip: 'Phrase instructions as a statement that can be true or false.',
  },
  choice: {
    title: 'Choice · one category',
    summary: 'Picks exactly one option and returns the distribution across all options.',
    whenToUse: [
      'Routing or tagging into a fixed set of buckets',
      'Options are mutually exclusive',
    ],
    example: {
      key: 'department',
      instructions: 'Which team should handle this',
      criteria: [
        { label: 'billing', description: 'Payment or subscription issues' },
        { label: 'technical', description: 'Bugs or integration problems' },
        { label: 'sales', description: 'Pricing or account questions' },
      ],
    },
    tip: 'Keep descriptions non-overlapping and include a catch-all like “other”.',
  },
  score: {
    title: 'Score · ordered scale',
    summary: 'Places the conversation on a scale you define, from lowest to highest.',
    whenToUse: [
      'Intensity or quality that has a natural order',
      'You want a comparable number across calls',
    ],
    example: {
      key: 'frustration',
      instructions: 'How frustrated the customer appears',
      criteria: [
        { label: '1', description: 'Calm, just stating facts' },
        { label: '2', description: 'Frustrated but civil' },
        { label: '3', description: 'Very angry, strong language' },
      ],
    },
    tip: 'List levels low → high; each should describe observable behaviour.',
  },
}
