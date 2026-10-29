import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'

export function renderImportDetailModal(content: ReactNode) {
  if (typeof document === 'undefined') return null
  return createPortal(content, document.body)
}
