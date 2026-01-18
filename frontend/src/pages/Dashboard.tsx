import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import {
  FileCheck,
  Clock,
  CheckCircle,
  Users,
  Phone,
  Database,
  Zap,
  Brain,
  Mic,
  Cloud,
  Rocket,
  ArrowRight,
  TrendingUp,
  Activity,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { EvaluationStatus, Evaluation } from '../types/api'
import { format } from 'date-fns'
import VoiceAIModelsCarousel from '../components/VoiceAIModelsCarousel'
import {
  Card,
  CardBody,
  CardHeader,
  Chip,
  Progress,
  Divider,
  Spinner,
  Avatar,
} from '@heroui/react'

export default function Dashboard() {
  const { data: evaluations, isLoading: evalLoading } = useQuery({
    queryKey: ['evaluations', 'list'],
    queryFn: () => apiClient.listEvaluations(0, 10),
  })

  const { data: agents } = useQuery({
    queryKey: ['agents', 'list'],
    queryFn: () => apiClient.listAgents(0, 100),
  })

  const { data: personas } = useQuery({
    queryKey: ['personas', 'list'],
    queryFn: () => apiClient.listPersonas(0, 100),
  })

  const { data: scenarios } = useQuery({
    queryKey: ['scenarios', 'list'],
    queryFn: () => apiClient.listScenarios(0, 100),
  })

  const { data: integrations } = useQuery({
    queryKey: ['integrations'],
    queryFn: async () => {
      try {
        const apiKey = localStorage.getItem('apiKey') || ''
        const API_BASE_URL = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000'
        const response = await fetch(`${API_BASE_URL}/api/v1/integrations`, {
          headers: {
            'X-API-Key': apiKey,
            'Content-Type': 'application/json',
          },
        })
        if (!response.ok) return []
        return response.json()
      } catch {
        return []
      }
    },
  })

  const stats = {
    totalEvaluations: evaluations?.length || 0,
    completedEvaluations: evaluations?.filter(
      (e: Evaluation) => e.status === EvaluationStatus.COMPLETED
    ).length || 0,
    pendingEvaluations: evaluations?.filter(
      (e: Evaluation) => e.status === EvaluationStatus.PENDING
    ).length || 0,
  }

  const recentEvaluations = evaluations?.slice(0, 5) || []

  const orgResources = {
    agents: agents?.length || 0,
    personas: personas?.length || 0,
    scenarios: scenarios?.length || 0,
    integrations: integrations?.length || 0,
    totalEvaluations: stats.totalEvaluations,
    completedEvaluations: stats.completedEvaluations,
  }

  const completionRate = stats.totalEvaluations > 0 
    ? Math.round((stats.completedEvaluations / stats.totalEvaluations) * 100) 
    : 0

  return (
    <div className="space-y-6">
      {/* Quick Start Guide */}
      <Card className="bg-gradient-to-br from-[#fef9c3] to-[#fefce8] border-none shadow-sm" radius="lg">
        <CardBody className="p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-3 bg-[#ca8a04] rounded-2xl">
              <Rocket className="h-6 w-6 text-white" />
            </div>
            <div>
              <h2 className="text-2xl font-bold text-gray-900">
                Start Testing in 5 Minutes
              </h2>
              <p className="text-sm text-gray-600 mt-1">
                Follow these quick steps to get started with voice AI testing
              </p>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <QuickStartCard
              icon={Brain}
              title="Configure AI Provider"
              description="Set up your AI provider credentials (OpenAI, Anthropic, etc.)"
              href="/integrations"
              step={1}
            />
            <QuickStartCard
              icon={Mic}
              title="Create Voice Bundle"
              description="Configure STT, LLM, and TTS models for your voice AI"
              href="/voicebundles"
              step={2}
            />
            <QuickStartCard
              icon={Cloud}
              title="Connect Data Sources"
              description="Connect your S3 bucket to manage audio files"
              href="/data-sources"
              step={3}
            />
            <QuickStartCard
              icon={Users}
              title="Create Test Agent"
              description="Set up agents, scenarios, and personas"
              href="/agents"
              step={4}
            />
          </div>
        </CardBody>
      </Card>

      {/* Voice AI Models Carousel */}
      <Card className="bg-gradient-to-br from-gray-50 to-gray-100/50 border-none shadow-sm" radius="lg">
        <CardBody className="p-6">
          <div className="mb-4">
            <h2 className="text-xl font-semibold text-gray-900 mb-1">
              Latest Voice AI Models
            </h2>
            <p className="text-sm text-gray-600">
              Explore the newest voice AI models from leading providers
            </p>
          </div>
          <VoiceAIModelsCarousel />
        </CardBody>
      </Card>

      {/* Stats Overview Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Stats Card */}
        <Card className="lg:col-span-2 shadow-sm" radius="lg">
          <CardHeader className="pb-0 pt-5 px-6">
            <div className="flex items-center gap-2">
              <Activity className="w-5 h-5 text-[#ca8a04]" />
              <h3 className="text-lg font-semibold text-gray-900">Evaluation Overview</h3>
            </div>
          </CardHeader>
          <CardBody className="p-6">
            <div className="grid grid-cols-3 gap-6">
              <StatItem
                label="Total Evaluations"
                value={stats.totalEvaluations}
                icon={FileCheck}
                color="blue"
              />
              <StatItem
                label="Completed"
                value={stats.completedEvaluations}
                icon={CheckCircle}
                color="green"
              />
              <StatItem
                label="Pending"
                value={stats.pendingEvaluations}
                icon={Clock}
                color="amber"
              />
            </div>
            
            <Divider className="my-6" />
            
            <div>
              <div className="flex justify-between items-center mb-2">
                <span className="text-sm text-gray-600">Completion Rate</span>
                <span className="text-sm font-semibold text-[#a16207]">{completionRate}%</span>
              </div>
              <Progress 
                value={completionRate} 
                className="h-2"
                classNames={{
                  indicator: "bg-gradient-to-r from-[#ca8a04] to-[#eab308]",
                  track: "bg-[#fef9c3]",
                }}
              />
            </div>
          </CardBody>
        </Card>

        {/* Quick Stats Card */}
        <Card className="shadow-sm" radius="lg">
          <CardHeader className="pb-0 pt-5 px-6">
            <div className="flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-[#34a853]" />
              <h3 className="text-lg font-semibold text-gray-900">Resources</h3>
            </div>
          </CardHeader>
          <CardBody className="p-6">
            <div className="space-y-4">
              <ResourceItem icon={Phone} label="Agents" value={orgResources.agents} href="/agents" color="blue" />
              <ResourceItem icon={Users} label="Personas" value={orgResources.personas} href="/personas" color="purple" />
              <ResourceItem icon={FileCheck} label="Scenarios" value={orgResources.scenarios} href="/scenarios" color="green" />
              <ResourceItem icon={Zap} label="Integrations" value={orgResources.integrations} href="/integrations" color="orange" />
            </div>
          </CardBody>
        </Card>
      </div>

      {/* Organization Resources */}
      <Card className="shadow-sm" radius="lg">
        <CardHeader className="pb-0 pt-5 px-6">
            <div className="flex items-center gap-2">
              <Database className="w-5 h-5 text-[#ca8a04]" />
              <h3 className="text-lg font-semibold text-gray-900">Organization Resources</h3>
            </div>
        </CardHeader>
        <CardBody className="p-6">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
            <ResourceCard icon={Phone} label="Agents" value={orgResources.agents} href="/agents" color="blue" />
            <ResourceCard icon={Users} label="Personas" value={orgResources.personas} href="/personas" color="purple" />
            <ResourceCard icon={FileCheck} label="Scenarios" value={orgResources.scenarios} href="/scenarios" color="green" />
            <ResourceCard icon={Zap} label="Integrations" value={orgResources.integrations} href="/integrations" color="orange" />
            <ResourceCard icon={Database} label="Evaluations" value={orgResources.totalEvaluations} href="/evaluations" color="indigo" />
            <ResourceCard icon={CheckCircle} label="Completed" value={orgResources.completedEvaluations} href="/evaluations?status=completed" color="emerald" />
          </div>
        </CardBody>
      </Card>

      {/* Recent Evaluations */}
      <Card className="shadow-sm" radius="lg">
        <CardHeader className="px-6 py-4">
          <div className="flex items-center justify-between w-full">
            <h3 className="text-lg font-semibold text-gray-900">Recent Evaluations</h3>
            <Link
              to="/evaluations"
              className="text-sm text-[#a16207] hover:text-[#854d0e] font-medium flex items-center gap-1"
            >
              View all
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </CardHeader>
        <Divider />
        <CardBody className="p-0">
          {evalLoading ? (
            <div className="flex justify-center py-12">
              <Spinner color="primary" size="lg" />
            </div>
          ) : recentEvaluations.length === 0 ? (
            <div className="text-center py-12">
              <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-[#fef9c3] flex items-center justify-center">
                <FileCheck className="h-8 w-8 text-[#ca8a04]" />
              </div>
              <p className="text-gray-500 mb-2">No evaluations yet</p>
              <Link
                to="/evaluations"
                className="text-[#a16207] hover:text-[#854d0e] font-medium text-sm"
              >
                Create your first evaluation →
              </Link>
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {recentEvaluations.map((evaluation: Evaluation) => (
                <Link
                  key={evaluation.id}
                  to={`/evaluations/${evaluation.id}`}
                  className="flex items-center justify-between px-6 py-4 hover:bg-gray-50 transition-colors"
                >
                  <div className="flex items-center gap-4">
                    <Avatar
                      name={evaluation.id.slice(0, 2).toUpperCase()}
                      size="sm"
                      className="bg-[#fef9c3] text-[#a16207]"
                    />
                    <div>
                      <p className="text-sm font-medium text-gray-900">
                        Evaluation {evaluation.id.slice(0, 8)}...
                      </p>
                      <p className="text-xs text-gray-500">
                        {format(new Date(evaluation.created_at), 'MMM d, yyyy HH:mm')}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-gray-500">{evaluation.evaluation_type}</span>
                    <StatusChip status={evaluation.status} />
                  </div>
                </Link>
              ))}
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}

function StatItem({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string
  value: number
  icon: React.ComponentType<{ className?: string }>
  color: 'blue' | 'green' | 'amber'
}) {
  const colorStyles = {
    blue: 'bg-[#fef9c3] text-[#a16207]',
    green: 'bg-[#e6f4ea] text-[#137333]',
    amber: 'bg-[#fef7e0] text-[#e37400]',
  }

  return (
    <div className="text-center">
      <div className={`w-12 h-12 mx-auto rounded-2xl ${colorStyles[color]} flex items-center justify-center mb-3`}>
        <Icon className="w-6 h-6" />
      </div>
      <div className="text-3xl font-bold text-gray-900">{value}</div>
      <div className="text-sm text-gray-500 mt-1">{label}</div>
    </div>
  )
}

function ResourceItem({
  icon: Icon,
  label,
  value,
  href,
  color,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: number
  href: string
  color: 'blue' | 'purple' | 'green' | 'orange'
}) {
  const colorStyles = {
    blue: 'bg-[#fef9c3] text-[#a16207]',
    purple: 'bg-[#f3e8ff] text-[#7c3aed]',
    green: 'bg-[#e6f4ea] text-[#137333]',
    orange: 'bg-[#fef3e2] text-[#ea8600]',
  }

  return (
    <Link to={href} className="flex items-center justify-between p-3 rounded-xl hover:bg-gray-50 transition-colors">
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-xl ${colorStyles[color]} flex items-center justify-center`}>
          <Icon className="w-5 h-5" />
        </div>
        <span className="text-sm font-medium text-gray-700">{label}</span>
      </div>
      <span className="text-lg font-bold text-gray-900">{value}</span>
    </Link>
  )
}

function ResourceCard({
  icon: Icon,
  label,
  value,
  href,
  color,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: number
  href: string
  color: string
}) {
  const colorStyles: Record<string, string> = {
    blue: 'bg-[#fef9c3] text-[#a16207]',
    purple: 'bg-[#f3e8ff] text-[#7c3aed]',
    green: 'bg-[#e6f4ea] text-[#137333]',
    orange: 'bg-[#fef3e2] text-[#ea8600]',
    indigo: 'bg-[#eef2ff] text-[#4f46e5]',
    emerald: 'bg-[#d1fae5] text-[#059669]',
  }

  return (
    <Link to={href}>
      <Card 
        className="hover:shadow-md transition-all duration-200 hover:scale-[1.02] cursor-pointer border-none bg-gray-50/50" 
        radius="lg"
        isPressable
      >
        <CardBody className="p-4 text-center">
          <div className={`w-12 h-12 mx-auto rounded-2xl ${colorStyles[color]} flex items-center justify-center mb-3`}>
            <Icon className="w-6 h-6" />
          </div>
          <div className="text-2xl font-bold text-gray-900">{value}</div>
          <div className="text-xs text-gray-500 mt-1">{label}</div>
        </CardBody>
      </Card>
    </Link>
  )
}

function QuickStartCard({
  icon: Icon,
  title,
  description,
  href,
  step,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  description: string
  href: string
  step: number
}) {
  return (
    <Link to={href}>
      <Card 
        className="h-full hover:shadow-md transition-all duration-200 hover:scale-[1.02] bg-white/80 backdrop-blur-sm border-none" 
        radius="lg"
        isPressable
      >
        <CardBody className="p-5">
          <div className="flex items-start gap-3 mb-3">
            <div className="w-10 h-10 rounded-xl bg-[#fef9c3] flex items-center justify-center flex-shrink-0">
              <Icon className="h-5 w-5 text-[#ca8a04]" />
            </div>
            <Chip 
              size="sm" 
              className="bg-[#ca8a04] text-white font-semibold"
              radius="full"
            >
              Step {step}
            </Chip>
          </div>
          <h3 className="text-base font-semibold text-gray-900 mb-2">{title}</h3>
          <p className="text-sm text-gray-600 mb-4">{description}</p>
          <div className="flex items-center gap-1 text-sm font-medium text-[#a16207]">
            Get started
            <ArrowRight className="h-4 w-4" />
          </div>
        </CardBody>
      </Card>
    </Link>
  )
}

function StatusChip({ status }: { status: EvaluationStatus }) {
  const statusConfig = {
    [EvaluationStatus.PENDING]: {
      color: 'warning' as const,
      label: 'Pending',
    },
    [EvaluationStatus.PROCESSING]: {
      color: 'primary' as const,
      label: 'Processing',
    },
    [EvaluationStatus.COMPLETED]: {
      color: 'success' as const,
      label: 'Completed',
    },
    [EvaluationStatus.FAILED]: {
      color: 'danger' as const,
      label: 'Failed',
    },
    [EvaluationStatus.CANCELLED]: {
      color: 'default' as const,
      label: 'Cancelled',
    },
  }

  const config = statusConfig[status]

  return (
    <Chip 
      size="sm" 
      color={config.color}
      variant="flat"
      radius="full"
      classNames={{
        base: config.color === 'success' ? 'bg-[#e6f4ea] text-[#137333]' :
              config.color === 'warning' ? 'bg-[#fef7e0] text-[#e37400]' :
              config.color === 'danger' ? 'bg-[#fce8e6] text-[#c5221f]' :
              config.color === 'primary' ? 'bg-[#fef9c3] text-[#a16207]' :
              'bg-gray-100 text-gray-600',
      }}
    >
      {config.label}
    </Chip>
  )
}
