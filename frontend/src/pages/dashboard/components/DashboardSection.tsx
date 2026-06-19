import { motion } from 'framer-motion'
import type { ReactNode } from 'react'

interface DashboardSectionProps {
  children: ReactNode
  delay?: number
}

export default function DashboardSection({ children, delay = 0 }: DashboardSectionProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay }}
    >
      {children}
    </motion.div>
  )
}
