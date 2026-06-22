import { useQuery } from '@tanstack/react-query'
import {
  Brain,
  Mic,
  Cloud,
  Users,
  Rocket,
  ArrowRight,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { Card, CardBody, Chip } from '@heroui/react'
import { apiClient } from '../../lib/api'
import VoiceAIModelsCarousel from '../../components/VoiceAIModelsCarousel'
import DashboardHighlights from './components/DashboardHighlights'

export default function Dashboard() {
  const { data: summary, isLoading } = useQuery({
    queryKey: ['dashboard', 'summary'],
    queryFn: () => apiClient.getDashboardSummary(),
    staleTime: 60 * 1000,
  })

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

      {/* Activity highlights */}
      <DashboardHighlights summary={summary} isLoading={isLoading} />

      {/* TTS Providers Carousel */}
      <Card className="bg-gradient-to-br from-gray-50 to-gray-100/50 border-none shadow-sm" radius="lg">
        <CardBody className="p-6">
          <div className="mb-4">
            <h2 className="text-xl font-semibold text-gray-900 mb-1">
              TTS Providers
            </h2>
            <p className="text-sm text-gray-600">
              Browse text-to-speech providers available in your model catalog
            </p>
          </div>
          <VoiceAIModelsCarousel />
        </CardBody>
      </Card>
    </div>
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
