import { Volume2 } from 'lucide-react'
import { MODEL_PROVIDER_CONFIG } from '../../config/providers'
import { ModelProvider } from '../../types/api'

interface ProviderLogoProps {
  provider: string
  size?: 'sm' | 'md' | 'lg'
  showFallback?: boolean
}

export function getProviderInfo(key: string): { label: string; logo: string | null } {
  const enumKey = key.toUpperCase() as keyof typeof ModelProvider
  const enumVal = ModelProvider[enumKey]
  if (enumVal && MODEL_PROVIDER_CONFIG[enumVal]) {
    return { label: MODEL_PROVIDER_CONFIG[enumVal].label, logo: MODEL_PROVIDER_CONFIG[enumVal].logo }
  }
  return { label: key.charAt(0).toUpperCase() + key.slice(1), logo: null }
}

export default function ProviderLogo({ provider, size = 'md', showFallback = true }: ProviderLogoProps) {
  const { logo, label } = getProviderInfo(provider)
  
  const dims = size === 'sm' ? 'w-5 h-5' : size === 'lg' ? 'w-10 h-10' : 'w-7 h-7'
  const containerDims = size === 'sm' ? 'w-6 h-6' : size === 'lg' ? 'w-12 h-12' : 'w-8 h-8'
  
  if (!logo) {
    if (!showFallback) return null
    return (
      <div className={`${containerDims} bg-gray-100 rounded-lg flex items-center justify-center border border-gray-200`}>
        <Volume2 className={`${size === 'sm' ? 'w-3 h-3' : 'w-4 h-4'} text-gray-400`} />
      </div>
    )
  }
  
  return (
    <div className={`${containerDims} bg-white rounded-lg flex items-center justify-center border border-gray-200 p-0.5`}>
      <img src={logo} alt={label} className={`${dims} object-contain`} />
    </div>
  )
}
