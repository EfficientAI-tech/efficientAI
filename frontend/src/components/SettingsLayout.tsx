import { Outlet, Link, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import {
  ArrowLeft,
  Key,
  Plug,
  Database,
  Phone,
  Shield,
  LogOut,
} from 'lucide-react'
import Logo from './Logo'
import WorkspaceSwitcher from './WorkspaceSwitcher'
import WalkthroughRail from './walkthrough/WalkthroughRail'
import { getSettingsReturnPath } from '../lib/settingsReturnPath'

const settingsNavigation = [
  { name: 'API Keys', href: '/settings/api-keys', icon: Key },
  { name: 'Integrations', href: '/settings/integrations', icon: Plug },
  { name: 'Cloud Storage', href: '/settings/cloud-storage', icon: Database },
  { name: 'Telephony', href: '/settings/telephony', icon: Phone },
  { name: 'Members and Access', href: '/settings/members', icon: Shield },
]

function isSettingsItemActive(href: string, pathname: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`)
}

export default function SettingsLayout() {
  const location = useLocation()
  const { logout } = useAuthStore()
  const backPath = getSettingsReturnPath()

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="hidden lg:fixed lg:inset-y-0 lg:z-40 lg:flex lg:w-64 lg:flex-col">
        <div className="flex h-full w-full flex-col overflow-hidden border-r border-gray-200 bg-white shadow-sm">
          <div className="flex h-16 flex-shrink-0 items-center border-b border-gray-200 px-4">
            <Logo />
          </div>
          <div className="flex-shrink-0 border-b border-gray-200 px-3 py-3">
            <Link
              to={backPath}
              className="flex items-center gap-2 rounded-md px-2 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 hover:text-gray-900"
            >
              <ArrowLeft className="h-4 w-4 text-gray-400" />
              Back to app
            </Link>
          </div>
          <div className="flex-shrink-0 border-b border-gray-200 px-3 py-3">
            <div className="mb-1.5 px-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
              Workspace
            </div>
            <WorkspaceSwitcher />
          </div>
          <nav className="flex-1 space-y-1 overflow-y-auto px-2 py-4">
            {settingsNavigation.map((item) => {
              const isActive = isSettingsItemActive(item.href, location.pathname)
              return (
                <Link
                  key={item.href}
                  to={item.href}
                  className={`group relative flex items-center overflow-hidden rounded-md px-2 py-2 text-sm font-medium ${
                    isActive
                      ? 'bg-gradient-to-r from-gray-900 via-gray-700 to-gray-400 text-white'
                      : 'text-gray-700 hover:bg-gray-50 hover:text-gray-900'
                  }`}
                >
                  <item.icon
                    className={`mr-3 h-5 w-5 flex-shrink-0 ${
                      isActive ? 'text-white' : 'text-gray-400 group-hover:text-gray-500'
                    }`}
                  />
                  {item.name}
                </Link>
              )
            })}
          </nav>
          <div className="flex-shrink-0 border-t border-gray-200 p-4">
            <button type="button" onClick={logout} className="group block w-full">
              <div className="flex items-center">
                <LogOut className="h-5 w-5 text-gray-400 group-hover:text-gray-500" />
                <span className="ml-3 text-sm font-medium text-gray-700 group-hover:text-gray-900">
                  Logout
                </span>
              </div>
            </button>
          </div>
        </div>
      </div>

      <div className="flex min-h-screen flex-col lg:pl-64">
        <div className="flex h-16 flex-shrink-0 items-center gap-3 border-b border-gray-200 bg-white px-4 shadow-sm lg:hidden">
          <Logo showText={false} />
          <Link
            to={backPath}
            className="inline-flex items-center gap-1 text-sm font-medium text-gray-700"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to app
          </Link>
        </div>
        <div className="flex gap-2 overflow-x-auto border-b border-gray-200 bg-white px-4 py-2 lg:hidden">
          {settingsNavigation.map((item) => {
            const isActive = isSettingsItemActive(item.href, location.pathname)
            return (
              <Link
                key={item.href}
                to={item.href}
                className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium ${
                  isActive
                    ? 'bg-gray-900 text-white'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                }`}
              >
                {item.name}
              </Link>
            )
          })}
        </div>
        <main className="flex-1 p-6">
          <div className="min-h-[calc(100vh-7rem)] min-w-0">
            <Outlet />
          </div>
        </main>
        <WalkthroughRail />
      </div>
    </div>
  )
}
