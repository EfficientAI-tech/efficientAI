import type { Modifier } from '@dnd-kit/core'

/** Keep drag translate inside the measured dnd container (stops infinite horizontal scroll). */
export const restrictToDashboardContainer: Modifier = ({
  containerNodeRect,
  draggingNodeRect,
  transform,
}) => {
  if (!containerNodeRect || !draggingNodeRect) return transform

  const next = { ...transform }

  if (draggingNodeRect.top + transform.y <= containerNodeRect.top) {
    next.y = containerNodeRect.top - draggingNodeRect.top
  } else if (draggingNodeRect.bottom + transform.y >= containerNodeRect.bottom) {
    next.y = containerNodeRect.bottom - draggingNodeRect.bottom
  }

  if (draggingNodeRect.left + transform.x <= containerNodeRect.left) {
    next.x = containerNodeRect.left - draggingNodeRect.left
  } else if (draggingNodeRect.right + transform.x >= containerNodeRect.right) {
    next.x = containerNodeRect.right - draggingNodeRect.right
  }

  return next
}