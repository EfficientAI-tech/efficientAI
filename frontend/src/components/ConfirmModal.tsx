import { AlertTriangle } from 'lucide-react'
import Button from './Button'

interface ConfirmModalProps {
  title: string
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  isOpen: boolean
  isLoading?: boolean
  onConfirm: () => void
  onCancel: () => void
  variant?: 'danger' | 'warning' | 'default'
}

export default function ConfirmModal({
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  isOpen,
  isLoading,
  onConfirm,
  onCancel,
  variant = 'danger',
}: ConfirmModalProps) {
  // Get styles for button and icon based on variant
  const getStyles = () => {
    switch (variant) {
      case 'danger':
        return {
          buttonClass: 'bg-[#fce8e6] hover:bg-[#fad2cf] text-[#c5221f] border-0',
          iconBgClass: 'bg-[#fce8e6]',
          iconClass: 'text-[#ea4335]'
        }
      case 'warning':
        return {
          buttonClass: 'bg-[#fef7e0] hover:bg-[#feefc3] text-[#e37400] border-0',
          iconBgClass: 'bg-[#fef7e0]',
          iconClass: 'text-[#f29900]'
        }
      default:
        return {
          buttonClass: 'bg-[#e8f0fe] hover:bg-[#d2e3fc] text-[#1a73e8] border-0',
          iconBgClass: 'bg-[#e8f0fe]',
          iconClass: 'text-[#1a73e8]'
        }
    }
  }

  const styles = getStyles()

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center p-4">
        {/* Backdrop */}
        <div
          className="fixed inset-0 bg-black/40 backdrop-blur-sm transition-opacity"
          onClick={onCancel}
        />
        
        {/* Modal Content */}
        <div className="relative bg-white rounded-2xl shadow-xl max-w-md w-full p-6">
          {/* Header */}
          <div className="flex items-center gap-3 mb-4">
            {(variant === 'danger' || variant === 'warning') && (
              <div className={`p-2.5 rounded-full ${styles.iconBgClass}`}>
                <AlertTriangle className={`w-5 h-5 ${styles.iconClass}`} />
              </div>
            )}
            <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
          </div>
          
          {/* Body */}
          {description && (
            <div className="mb-6">
              <p className="text-gray-600">{description}</p>
            </div>
          )}
          
          {/* Footer */}
          <div className="flex justify-end gap-3">
            <Button 
              variant="ghost" 
              onClick={onCancel}
              disabled={isLoading}
            >
              {cancelLabel}
            </Button>
            <button
              onClick={onConfirm}
              disabled={isLoading}
              className={`px-4 py-2 rounded-full font-semibold transition-colors disabled:opacity-50 ${styles.buttonClass}`}
            >
              {isLoading ? (
                <span className="flex items-center gap-2">
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  {confirmLabel}
                </span>
              ) : (
                confirmLabel
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
