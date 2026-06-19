import { Chip } from '@heroui/react'
import { EvaluationStatus } from '../../../types/api'

export default function StatusChip({ status }: { status: EvaluationStatus }) {
  const statusConfig = {
    [EvaluationStatus.PENDING]: { color: 'warning' as const, label: 'Pending' },
    [EvaluationStatus.PROCESSING]: { color: 'primary' as const, label: 'Processing' },
    [EvaluationStatus.COMPLETED]: { color: 'success' as const, label: 'Completed' },
    [EvaluationStatus.FAILED]: { color: 'danger' as const, label: 'Failed' },
    [EvaluationStatus.CANCELLED]: { color: 'default' as const, label: 'Cancelled' },
  }

  const config = statusConfig[status]

  return (
    <Chip
      size="sm"
      color={config.color}
      variant="flat"
      radius="full"
      classNames={{
        base:
          config.color === 'success'
            ? 'bg-[#e6f4ea] text-[#137333]'
            : config.color === 'warning'
              ? 'bg-[#fef7e0] text-[#e37400]'
              : config.color === 'danger'
                ? 'bg-[#fce8e6] text-[#c5221f]'
                : config.color === 'primary'
                  ? 'bg-[#fef9c3] text-[#a16207]'
                  : 'bg-gray-100 text-gray-600',
      }}
    >
      {config.label}
    </Chip>
  )
}
