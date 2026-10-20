import { afterEach, describe, expect, it, vi } from 'vitest'
import { copyTextToClipboard } from './clipboard'

function stubInsecureClipboard(execCommand: () => boolean) {
  const textarea = {
    value: '',
    style: {} as { position?: string; opacity?: string },
    select: () => {},
  }
  vi.stubGlobal('window', { isSecureContext: false })
  vi.stubGlobal('document', {
    createElement: () => textarea,
    body: { appendChild: () => {}, removeChild: () => {} },
    execCommand,
  })
}

describe('copyTextToClipboard', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('calls onSuccess only when the fallback copy succeeds', () => {
    stubInsecureClipboard(() => true)
    const onSuccess = vi.fn()
    const onError = vi.fn()
    copyTextToClipboard('https://example.test/blind-test/abc', onSuccess, onError)
    expect(onSuccess).toHaveBeenCalledOnce()
    expect(onError).not.toHaveBeenCalled()
  })

  it('calls onError when execCommand returns false', () => {
    stubInsecureClipboard(() => false)
    const onSuccess = vi.fn()
    const onError = vi.fn()
    copyTextToClipboard('https://example.test/blind-test/abc', onSuccess, onError)
    expect(onSuccess).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledOnce()
  })
})
