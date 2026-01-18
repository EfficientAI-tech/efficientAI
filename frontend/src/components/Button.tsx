import { ReactNode, MouseEvent, FormEvent } from 'react'
import { Button as HeroButton } from '@heroui/react'
import { PressEvent } from '@react-types/shared'
import { clsx } from 'clsx'

interface ButtonProps {
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger' | 'success'
  size?: 'sm' | 'md' | 'lg'
  isLoading?: boolean
  leftIcon?: ReactNode
  rightIcon?: ReactNode
  children: ReactNode
  className?: string
  disabled?: boolean
  type?: 'button' | 'submit' | 'reset'
  onClick?: (e?: MouseEvent<HTMLButtonElement> | FormEvent | PressEvent | any) => any
  title?: string  // For accessibility/tooltip
}

export default function Button({
  variant = 'primary',
  size = 'md',
  isLoading = false,
  leftIcon,
  rightIcon,
  children,
  className,
  disabled,
  type = 'button',
  onClick,
  title,
}: ButtonProps) {
  // Map our variants to HeroUI color and variant props with light/tonal styles
  const getHeroUIProps = () => {
    switch (variant) {
      case 'primary':
        return { 
          color: 'primary' as const, 
          variant: 'flat' as const,
          customClass: 'bg-[#fef9c3] hover:bg-[#fef08a] text-[#a16207] font-semibold border border-[#facc15]'
        }
      case 'secondary':
        return { 
          color: 'default' as const, 
          variant: 'flat' as const,
          customClass: 'bg-gray-100 hover:bg-gray-200 text-gray-700'
        }
      case 'outline':
        return { 
          color: 'primary' as const, 
          variant: 'bordered' as const,
          customClass: 'border-2 border-[#ca8a04] text-[#a16207] bg-transparent hover:bg-[#fefce8]'
        }
      case 'ghost':
        return { 
          color: 'default' as const, 
          variant: 'light' as const,
          customClass: 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
        }
      case 'danger':
        return { 
          color: 'danger' as const, 
          variant: 'flat' as const,
          customClass: 'bg-[#fce8e6] hover:bg-[#fad2cf] text-[#c5221f] font-semibold'
        }
      case 'success':
        return { 
          color: 'success' as const, 
          variant: 'flat' as const,
          customClass: 'bg-[#e6f4ea] hover:bg-[#ceead6] text-[#137333] font-semibold'
        }
      default:
        return { 
          color: 'primary' as const, 
          variant: 'flat' as const,
          customClass: 'bg-[#fef9c3] hover:bg-[#fef08a] text-[#a16207] border border-[#facc15]'
        }
    }
  }

  const heroUIProps = getHeroUIProps()

  // Handle press event and convert to something that can be used by onClick handlers
  const handlePress = (e: PressEvent) => {
    if (onClick) {
      // Create a synthetic event-like object that has stopPropagation
      const syntheticEvent = {
        ...e,
        preventDefault: () => {},
        stopPropagation: () => {
          // PressEvent from react-aria has continuePropagation, we invert the logic
          e.continuePropagation()
        },
      }
      onClick(syntheticEvent)
    }
  }

  return (
    <HeroButton
      color={heroUIProps.color}
      variant={heroUIProps.variant}
      size={size}
      radius="full"
      isLoading={isLoading}
      isDisabled={disabled}
      startContent={leftIcon}
      endContent={rightIcon}
      className={clsx(heroUIProps.customClass, 'transition-all duration-200', className)}
      type={type}
      onPress={handlePress}
      title={title}
      aria-label={title}
    >
      {children}
    </HeroButton>
  )
}

