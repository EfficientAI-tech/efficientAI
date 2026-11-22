import { describe, expect, it } from 'vitest'
import { SseParser } from '../../lib/copilotApi'
import { pageContextFromPath } from './pageContext'

describe('SseParser', () => {
  it('parses events split across chunks and skips keep-alives', () => {
    const parser = new SseParser()
    expect(parser.push('id: 1\nevent: token\ndata: {"te')).toEqual([])
    expect(parser.push('xt":"Hi"}\n\n: keep-alive\n\nevent: done\r\ndata: {"message_id":"m","status":"complete"}\r\n\r\n')).toEqual([
      { event: 'token', data: { text: 'Hi' } },
      { event: 'done', data: { message_id: 'm', status: 'complete' } },
    ])
  })

  it('skips malformed data without breaking later events', () => {
    const parser = new SseParser()
    expect(parser.push('event: token\ndata: {nope\n\nevent: token\ndata: {"text":"ok"}\n\n')).toEqual([
      { event: 'token', data: { text: 'ok' } },
    ])
  })
})

describe('pageContextFromPath', () => {
  it('recognises import evaluations before imports', () => {
    expect(pageContextFromPath('/call-imports/abc/evaluations/def')).toMatchObject({
      entity_type: 'import_evaluation',
      entity_id: 'def',
    })
    expect(pageContextFromPath('/call-imports/abc')).toMatchObject({ entity_type: 'call_import', entity_id: 'abc' })
    expect(pageContextFromPath('/call-imports/tags')).toEqual({ route: '/call-imports/tags' })
  })

  it('falls back to just the route', () => {
    expect(pageContextFromPath('/usage')).toEqual({ route: '/usage' })
    expect(pageContextFromPath('/agents/42')).toMatchObject({ entity_type: 'agent', entity_id: '42' })
  })
})
