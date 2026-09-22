import { describe, expect, it } from 'vitest'
import { summarizeFlowchartError } from './apiErrors'

describe('summarizeFlowchartError', () => {
  it('returns a short summary and strips python tracebacks', () => {
    const raw = [
      'Generation failed for openai/gemini-1.5-flash: litellm.NotFoundError: OpenAIException - The model `gemini-1.5-flash` does not exist.',
      'Traceback (most recent call last):',
      '  File "/app/service.py", line 1, in run',
      '    raise Error()',
    ].join('\n')

    const result = summarizeFlowchartError(raw)

    expect(result.summary).toContain('gemini-1.5-flash')
    expect(result.summary).not.toContain('Traceback')
    expect(result.details).toContain('Generation failed for openai/gemini-1.5-flash')
    expect(result.details).not.toContain('Traceback')
  })
})
