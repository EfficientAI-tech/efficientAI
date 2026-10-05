import { TelephonyProvider } from '../types/api'
import { getTelephonyProviderLabel, getTelephonyProviderLogo } from '../config/providers'

function resolveProvider(value: string | null | undefined): TelephonyProvider | null {
  const key = (value || '').trim().toLowerCase()
  if (!key) return null
  return Object.values(TelephonyProvider).includes(key as TelephonyProvider)
    ? (key as TelephonyProvider)
    : null
}

type TelephonyProviderBrandProps = {
  provider: string | TelephonyProvider | null | undefined
  size?: 'sm' | 'md'
  showLabel?: boolean
  className?: string
}

export default function TelephonyProviderBrand({
  provider,
  size = 'md',
  showLabel = true,
  className = '',
}: TelephonyProviderBrandProps) {
  const enumVal = resolveProvider(typeof provider === 'string' ? provider : provider ?? undefined)
  const label = enumVal
    ? getTelephonyProviderLabel(enumVal)
    : (provider || '—').toString()
  const logo = enumVal ? getTelephonyProviderLogo(enumVal) : null
  const imgClass = size === 'sm' ? 'h-5 w-5' : 'h-6 w-6'

  return (
    <div className={`flex items-center gap-2 min-w-0 ${className}`}>
      {logo ? (
        <img src={logo} alt="" className={`${imgClass} object-contain shrink-0`} aria-hidden />
      ) : null}
      {showLabel ? <span className="truncate text-inherit">{label}</span> : null}
    </div>
  )
}
