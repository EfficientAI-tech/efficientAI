import { Link } from 'react-router-dom'
import { Radio } from 'lucide-react'
import { callImportIdFromPartialTags } from '../constants'

type Props = {
  tags?: string[] | null
  className?: string
  stopPropagation?: boolean
  label?: string
  variant?: 'link' | 'pill'
}

export default function CallImportPartialLink({
  tags,
  className = '',
  stopPropagation = false,
  label = 'Linked Evaluation',
  variant = 'link',
}: Props) {
  const importId = callImportIdFromPartialTags(tags)
  if (!importId) return null
  const pillClass =
    'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-900 border border-amber-200 hover:bg-amber-100 no-underline whitespace-nowrap'
  const linkClass =
    'inline-flex items-center gap-1 text-xs font-medium text-primary-700 hover:text-primary-800 hover:underline'
  return (
    <Link
      to={`/call-imports/${importId}`}
      className={`${variant === 'pill' ? pillClass : linkClass} ${className}`}
      onClick={stopPropagation ? (e) => e.stopPropagation() : undefined}
    >
      <Radio className="h-3 w-3 shrink-0" aria-hidden />
      {label}
    </Link>
  )
}
