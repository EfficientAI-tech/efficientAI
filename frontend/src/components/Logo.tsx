import faviconDark from '/favicon_dark.png'

interface LogoProps {
  className?: string
  showText?: boolean
  textSize?: 'sm' | 'md' | 'lg' | 'xl'
}

export default function Logo({ className = '', showText = true, textSize = 'md' }: LogoProps) {
  const textSizeClasses = {
    sm: 'text-lg',
    md: 'text-xl',
    lg: 'text-2xl',
    xl: 'text-3xl',
  }

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <img src={faviconDark} alt="EfficientAI" className="h-8 w-8" />
      {showText && (
        <h2 className={`font-bold ${textSizeClasses[textSize]}`}>
          <span className="text-gray-900">Efficient</span>
          <span className="text-primary-600">AI</span>
        </h2>
      )}
    </div>
  )
}

