import {
  Modal,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Button,
} from '@heroui/react'
import { AlertTriangle } from 'lucide-react'

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
  // Get Google-style light colors for button and icon
  const getStyles = () => {
    switch (variant) {
      case 'danger':
        return {
          buttonClass: 'bg-[#fce8e6] hover:bg-[#fad2cf] text-[#c5221f] font-semibold',
          iconBgClass: 'bg-[#fce8e6]',
          iconClass: 'text-[#ea4335]'
        }
      case 'warning':
        return {
          buttonClass: 'bg-[#fef7e0] hover:bg-[#feefc3] text-[#e37400] font-semibold',
          iconBgClass: 'bg-[#fef7e0]',
          iconClass: 'text-[#f29900]'
        }
      default:
        return {
          buttonClass: 'bg-[#e8f0fe] hover:bg-[#d2e3fc] text-[#1a73e8] font-semibold',
          iconBgClass: 'bg-[#e8f0fe]',
          iconClass: 'text-[#1a73e8]'
        }
    }
  }

  const styles = getStyles()

  return (
    <Modal 
      isOpen={isOpen} 
      onOpenChange={(open) => !open && onCancel()}
      backdrop="blur"
      radius="lg"
      classNames={{
        backdrop: "bg-black/40",
        base: "rounded-2xl",
      }}
    >
      <ModalContent>
        {() => (
          <>
            <ModalHeader className="flex flex-col gap-1">
              <div className="flex items-center gap-3">
                {variant === 'danger' && (
                  <div className={`p-2 rounded-full ${styles.iconBgClass}`}>
                    <AlertTriangle className={`w-5 h-5 ${styles.iconClass}`} />
                  </div>
                )}
                <span className="text-gray-900 font-semibold">{title}</span>
              </div>
            </ModalHeader>
            <ModalBody>
              {description && (
                <p className="text-gray-600">{description}</p>
              )}
            </ModalBody>
            <ModalFooter>
              <Button 
                variant="light" 
                onPress={onCancel}
                isDisabled={isLoading}
                className="text-gray-600 hover:bg-gray-100"
                radius="full"
              >
                {cancelLabel}
              </Button>
              <Button 
                onPress={onConfirm}
                isLoading={isLoading}
                className={styles.buttonClass}
                radius="full"
              >
                {confirmLabel}
              </Button>
            </ModalFooter>
          </>
        )}
      </ModalContent>
    </Modal>
  )
}

