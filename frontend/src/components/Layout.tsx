import { Outlet, Link, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useAgentStore, type Agent } from '../store/agentStore'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import {
  LayoutDashboard,
  FileCheck,
  FolderSync,
  LogOut,
  Menu,
  Phone,
  Users,
  FileText,
  Shield,
  UserCircle,
  Play,
  BarChart3,
  Plug,
  ChevronRight,
  ChevronDown,
  Database,
  Settings,
  Mic,
  Brain,
  Bot,
} from 'lucide-react'
import { useState, useEffect } from 'react'
import Logo from './Logo'

interface NavItem {
  name: string
  href: string
  icon: React.ComponentType<{ className?: string }>
}

interface NavSection {
  title: string
  items: NavItem[]
  icon: React.ComponentType<{ className?: string }>
}

const navigationSections: NavSection[] = [
  {
    title: 'Simulations',
    icon: Play,
    items: [
      { name: 'Agents', href: '/agents', icon: Bot },
      { name: 'Personas', href: '/personas', icon: Users },
      { name: 'Scenarios', href: '/scenarios', icon: FileText },
      { name: 'Metrics Management', href: '/metrics-management', icon: BarChart3 },
    ],
  },
  {
    title: 'Evaluations',
    icon: FileCheck,
    items: [
      { name: 'Manual Transcriptions', href: '/evaluations', icon: Mic },
      { name: 'Batch Jobs', href: '/batch', icon: FolderSync },
      { name: 'Evaluators', href: '/evaluate-test-agents', icon: Mic },
    ],
  },
  {
    title: 'Results',
    icon: BarChart3,
    items: [
      { name: 'Evaluation Results', href: '/results', icon: BarChart3 },
    ],
  },
  {
    title: 'Configurations',
    icon: Settings,
    items: [
      { name: 'S3 Integration', href: '/data-sources', icon: Database },
      { name: 'AI Providers', href: '/ai-providers', icon: Brain },
      { name: 'VoiceBundle', href: '/voicebundles', icon: Mic },
      { name: 'Integrations', href: '/integrations', icon: Plug },
    ],
  },
]

const otherNavigation: NavItem[] = [
  { name: 'Dashboard', href: '/', icon: LayoutDashboard },
]

const bottomNavigation = [
  { name: 'IAM', href: '/iam', icon: Shield },
  { name: 'Profile', href: '/profile', icon: UserCircle }
]

export default function Layout() {
  const location = useLocation()
  const { logout } = useAuthStore()
  const { selectedAgent, setSelectedAgent } = useAgentStore()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [showAgentDropdown, setShowAgentDropdown] = useState(false)

  // Fetch agents
  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => apiClient.listAgents(),
  })

  // Auto-select first agent if none is selected and agents are available
  useEffect(() => {
    if (!selectedAgent && agents.length > 0) {
      setSelectedAgent(agents[0])
    }
  }, [agents, selectedAgent, setSelectedAgent])

  // Clear selection if selected agent no longer exists
  useEffect(() => {
    if (selectedAgent && !agents.find((a: Agent) => a.id === selectedAgent.id)) {
      if (agents.length > 0) {
        setSelectedAgent(agents[0])
      } else {
        setSelectedAgent(null)
      }
    }
  }, [agents, selectedAgent, setSelectedAgent])

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Mobile sidebar */}
      <div
        className={`fixed inset-0 z-40 lg:hidden ${sidebarOpen ? '' : 'pointer-events-none'
          }`}
      >
        <div
          className={`fixed inset-0 bg-gray-600 bg-opacity-75 transition-opacity ${sidebarOpen ? 'opacity-100' : 'opacity-0'
            }`}
          onClick={() => setSidebarOpen(false)}
        />
        <div
          className={`fixed inset-y-0 left-0 flex w-64 flex-col bg-white shadow-xl transition-transform duration-300 ease-in-out ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'
            }`}
        >
          <SidebarContent onLogout={logout} location={location} />
        </div>
      </div>

      {/* Desktop sidebar */}
      <div className="hidden lg:fixed lg:inset-y-0 lg:flex lg:w-64 lg:flex-col">
        <div className="flex flex-col flex-grow bg-white border-r border-gray-200 shadow-sm">
          <SidebarContent onLogout={logout} location={location} />
        </div>
      </div>

      {/* Main content */}
      <div className="lg:pl-64 flex flex-col flex-1">
        {/* Top bar */}
        <div className="sticky top-0 z-10 flex-shrink-0 flex h-16 bg-white shadow-sm border-b border-gray-200">
          <button
            type="button"
            className="px-4 text-gray-500 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-gray-500 lg:hidden"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu className="h-6 w-6" />
          </button>
          <div className="flex-1 px-4 flex justify-between items-center">
            {/* Agent Selector */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowAgentDropdown(!showAgentDropdown)}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              >
                <Phone className="h-4 w-4 text-gray-500" />
                <span className="min-w-[120px] text-left">
                  {selectedAgent ? selectedAgent.name : 'Select Agent'}
                </span>
                <ChevronDown className="h-4 w-4 text-gray-500" />
              </button>

              {/* Dropdown */}
              {showAgentDropdown && (
                <>
                  <div
                    className="fixed inset-0 z-10"
                    onClick={() => setShowAgentDropdown(false)}
                  />
                  <div className="absolute left-0 mt-2 w-64 bg-white rounded-lg shadow-lg border border-gray-200 z-20 max-h-96 overflow-y-auto">
                    {agents.length === 0 ? (
                      <div className="px-4 py-3 text-center">
                        <p className="text-sm text-gray-500 mb-3">No agents available</p>
                        <Link
                          to="/agents"
                          onClick={() => setShowAgentDropdown(false)}
                          className="inline-block text-sm text-primary-600 hover:text-primary-700 font-medium"
                        >
                          Create your first agent →
                        </Link>
                      </div>
                    ) : (
                      <>
                        {agents.map((agent: Agent) => (
                          <button
                            key={agent.id}
                            type="button"
                            onClick={() => {
                              setSelectedAgent(agent)
                              setShowAgentDropdown(false)
                            }}
                            className={`w-full px-4 py-3 text-left hover:bg-gray-50 transition-colors ${selectedAgent?.id === agent.id
                              ? 'bg-primary-50 border-l-4 border-primary-500'
                              : 'border-l-4 border-transparent'
                              }`}
                          >
                            <div className="flex items-center justify-between">
                              <div>
                                <div className="text-sm font-medium text-gray-900">
                                  {agent.name}
                                </div>
                                <div className="text-xs text-gray-500 mt-0.5">
                                  {agent.phone_number} • {agent.language}
                                </div>
                              </div>
                              {selectedAgent?.id === agent.id && (
                                <div className="h-2 w-2 bg-primary-500 rounded-full" />
                              )}
                            </div>
                          </button>
                        ))}
                        <div className="border-t border-gray-200 px-4 py-2">
                          <Link
                            to="/agents"
                            onClick={() => setShowAgentDropdown(false)}
                            className="text-sm text-primary-600 hover:text-primary-700 font-medium"
                          >
                            Manage Agents →
                          </Link>
                        </div>
                      </>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Page content */}
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function SidebarContent({
  onLogout,
  location,
}: {
  onLogout: () => void
  location: ReturnType<typeof useLocation>
}) {
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(['Simulations', 'Evaluations', 'Results', 'Configurations'])
  )

  const toggleSection = (title: string) => {
    const newExpanded = new Set(expandedSections)
    if (newExpanded.has(title)) {
      newExpanded.delete(title)
    } else {
      newExpanded.add(title)
    }
    setExpandedSections(newExpanded)
  }

  const isSectionActive = (section: NavSection) => {
    return section.items.some(item => location.pathname === item.href)
  }

  return (
    <>
      <div className="flex items-center flex-shrink-0 px-4 h-16 border-b border-gray-200">
        <Logo />
      </div>
      <div className="flex-1 flex flex-col pb-4 overflow-y-auto">
        <nav className="flex-1 px-2 space-y-1">
          {/* Other Navigation */}
          {otherNavigation.map((item) => {
            const isActive = location.pathname === item.href
            return (
              <Link
                key={item.name}
                to={item.href}
                className={`group flex items-center px-2 py-2 text-sm font-medium rounded-md ${isActive
                  ? 'bg-gray-100 text-gray-900'
                  : 'text-gray-700 hover:bg-gray-50 hover:text-gray-900'
                  }`}
              >
                <item.icon
                  className={`mr-3 flex-shrink-0 h-5 w-5 ${isActive ? 'text-gray-700' : 'text-gray-400 group-hover:text-gray-500'
                    }`}
                />
                {item.name}
              </Link>
            )
          })}

          {/* Navigation Sections */}
          <div className="mt-4 space-y-1">
            {navigationSections.map((section) => {
              const isExpanded = expandedSections.has(section.title)
              const isActive = isSectionActive(section)
              const SectionIcon = section.icon

              return (
                <div key={section.title}>
                  <button
                    onClick={() => toggleSection(section.title)}
                    className={`w-full group flex items-center justify-between px-2 py-2 text-sm font-medium rounded-md ${isActive
                      ? 'bg-gray-100 text-gray-900'
                      : 'text-gray-700 hover:bg-gray-50 hover:text-gray-900'
                      }`}
                  >
                    <div className="flex items-center">
                      <SectionIcon
                        className={`mr-3 flex-shrink-0 h-5 w-5 ${isActive ? 'text-gray-700' : 'text-gray-400 group-hover:text-gray-500'
                          }`}
                      />
                      {section.title}
                    </div>
                    {isExpanded ? (
                      <ChevronDown className="h-4 w-4 text-gray-400" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-gray-400" />
                    )}
                  </button>
                  {isExpanded && (
                    <div className="ml-6 mt-1 space-y-1">
                      {section.items.map((item) => {
                        const isItemActive = location.pathname === item.href
                        return (
                          <Link
                            key={item.name}
                            to={item.href}
                            className={`group flex items-center px-2 py-2 text-sm font-medium rounded-md ${isItemActive
                              ? 'bg-gray-100 text-gray-900'
                              : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                              }`}
                          >
                            <item.icon
                              className={`mr-3 flex-shrink-0 h-4 w-4 ${isItemActive ? 'text-gray-700' : 'text-gray-400 group-hover:text-gray-500'
                                }`}
                            />
                            {item.name}
                          </Link>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </nav>
        <nav className="mt-5 px-2 space-y-1 border-t border-gray-200 pt-4">
          {bottomNavigation.map((item) => {
            const isActive = location.pathname === item.href
            return (
              <Link
                key={item.name}
                to={item.href}
                className={`group flex items-center px-2 py-2 text-sm font-medium rounded-md ${isActive
                  ? 'bg-gray-100 text-gray-900'
                  : 'text-gray-700 hover:bg-gray-50 hover:text-gray-900'
                  }`}
              >
                <item.icon
                  className={`mr-3 flex-shrink-0 h-5 w-5 ${isActive ? 'text-gray-700' : 'text-gray-400 group-hover:text-gray-500'
                    }`}
                />
                {item.name}
              </Link>
            )
          })}
        </nav>
      </div>
      <div className="flex-shrink-0 flex border-t border-gray-200 p-4">
        <button
          onClick={onLogout}
          className="flex-shrink-0 w-full group block"
        >
          <div className="flex items-center">
            <LogOut className="h-5 w-5 text-gray-400 group-hover:text-gray-500" />
            <span className="ml-3 text-sm font-medium text-gray-700 group-hover:text-gray-900">
              Logout
            </span>
          </div>
        </button>
      </div>
    </>
  )
}

