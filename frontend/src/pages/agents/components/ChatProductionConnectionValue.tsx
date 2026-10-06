import TelephonyProviderBrand from '../../../components/TelephonyProviderBrand'
import type { ChatProductionConnectionDisplay } from '../../../lib/chatProductionConnection'

type Props = {
  display: ChatProductionConnectionDisplay
  compact?: boolean
}

export default function ChatProductionConnectionValue({ display, compact = false }: Props) {
  const iconBox = compact ? 'h-6 w-6' : 'h-7 w-7'

  const detailTitle = display.detail ? `${display.headline} · ${display.detail}` : display.headline

  return (
    <div
      className="flex items-start gap-2 min-w-0 max-w-full overflow-hidden"
      title={detailTitle}
    >
      {display.telephonyProvider ? (
        <TelephonyProviderBrand
          provider={display.telephonyProvider}
          showLabel={false}
          size={compact ? 'sm' : 'md'}
          className="shrink-0"
        />
      ) : display.platformLogo ? (
        <span
          className={`${iconBox} shrink-0 flex items-center justify-center rounded-md border border-gray-200 bg-white p-0.5`}
        >
          <img src={display.platformLogo} alt="" className="h-full w-full object-contain" aria-hidden />
        </span>
      ) : null}
      <div className="min-w-0 flex-1 overflow-hidden">
        <p className="truncate font-medium text-gray-900 text-sm">{display.headline}</p>
        {display.detail ? (
          <p className="text-xs text-gray-500 truncate mt-0.5 font-normal">{display.detail}</p>
        ) : null}
      </div>
    </div>
  )
}
