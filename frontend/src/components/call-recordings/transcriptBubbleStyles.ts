export function transcriptBubbleClass(isUser: boolean, width: '80' | '85' = '85'): string {
  const maxW = width === '80' ? 'max-w-[80%]' : 'max-w-[85%]'
  if (isUser) {
    return `${maxW} rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2.5 text-white`
  }
  return `${maxW} rounded-2xl rounded-bl-sm border border-gray-200 bg-gray-100 px-4 py-2.5 text-gray-800`
}

export function transcriptMetaClass(isUser: boolean): string {
  return `mb-0.5 flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-wider ${
    isUser ? 'text-indigo-200' : 'text-gray-400'
  }`
}
