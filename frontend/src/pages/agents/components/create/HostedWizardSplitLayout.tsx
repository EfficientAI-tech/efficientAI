import type { ReactNode } from 'react'

import { WizardStepHeader } from './WizardStepHeader'

interface HostedWizardSplitLayoutProps {
  title: string
  subtitle: string
  leftTitle: string
  leftHint?: string
  left: ReactNode
  right: ReactNode
}

export default function HostedWizardSplitLayout({
  title,
  subtitle,
  leftTitle,
  leftHint,
  left,
  right,
}: HostedWizardSplitLayoutProps) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <WizardStepHeader title={title} subtitle={subtitle} />
      <div className="mt-4 flex min-h-0 flex-1 flex-col gap-4 lg:flex-row lg:gap-6">
        <div className="flex min-h-[280px] flex-1 flex-col min-w-0 lg:min-h-0">
          <div className="mb-2 flex items-baseline justify-between gap-2">
            <label className="text-sm font-medium text-gray-900">{leftTitle}</label>
            {leftHint ? <span className="text-xs text-gray-500">{leftHint}</span> : null}
          </div>
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-gray-200 bg-gray-50/80">
            {left}
          </div>
        </div>
        <div className="flex w-full shrink-0 flex-col gap-4 overflow-y-auto lg:w-[22rem] lg:max-h-full lg:pr-1">
          {right}
        </div>
      </div>
    </div>
  )
}

export function HostedPromptTextarea({
  value,
  onChange,
  readOnly,
  placeholder,
  mono = true,
}: {
  value: string
  onChange?: (value: string) => void
  readOnly?: boolean
  placeholder?: string
  mono?: boolean
}) {
  return (
    <textarea
      value={value}
      readOnly={readOnly}
      onChange={onChange ? (e) => onChange(e.target.value) : undefined}
      placeholder={placeholder}
      className={`h-full min-h-[260px] w-full flex-1 resize-none border-0 bg-transparent p-4 text-sm text-gray-800 focus:outline-none focus:ring-0 lg:min-h-0 ${
        mono ? 'font-mono leading-relaxed' : ''
      } ${readOnly ? 'cursor-default' : ''}`}
    />
  )
}
