import { Link } from 'react-router-dom'
import {
  Brain,
  Mic,
  Cloud,
  Users,
  Rocket,
  ArrowRight,
  CheckCircle2,
  Circle,
} from 'lucide-react'
import { Card, CardBody, Chip } from '@heroui/react'
import type { DashboardSummary } from '../../../types/api'

interface SetupStep {
  key: keyof DashboardSummary['setup_progress']
  icon: React.ComponentType<{ className?: string }>
  title: string
  description: string
  href: string
  step: number
}

const SETUP_STEPS: SetupStep[] = [
  {
    key: 'has_integration',
    icon: Brain,
    title: 'Configure AI Provider',
    description: 'Set up your AI provider credentials (OpenAI, Anthropic, etc.)',
    href: '/integrations',
    step: 1,
  },
  {
    key: 'has_voice_bundle',
    icon: Mic,
    title: 'Create Voice Bundle',
    description: 'Configure STT, LLM, and TTS models for your voice AI',
    href: '/voicebundles',
    step: 2,
  },
  {
    key: 'has_agent',
    icon: Users,
    title: 'Create Test Agent',
    description: 'Set up agents, scenarios, and personas',
    href: '/agents',
    step: 3,
  },
  {
    key: 'has_evaluation',
    icon: Cloud,
    title: 'Run First Evaluation',
    description: 'Start testing your voice AI with an evaluation',
    href: '/metrics',
    step: 4,
  },
]

interface SetupProgressHeroProps {
  setupProgress: DashboardSummary['setup_progress']
  compact?: boolean
}

export default function SetupProgressHero({ setupProgress, compact = false }: SetupProgressHeroProps) {
  const completedCount = SETUP_STEPS.filter((step) => setupProgress[step.key]).length
  const incompleteSteps = SETUP_STEPS.filter((step) => !setupProgress[step.key])
  const stepsToShow = compact ? incompleteSteps : SETUP_STEPS

  if (compact && stepsToShow.length === 0) {
    return null
  }

  return (
    <Card
      className={`border-none shadow-sm ${
        compact
          ? 'bg-white'
          : 'bg-gradient-to-br from-[#fef9c3] to-[#fefce8]'
      }`}
      radius="lg"
    >
      <CardBody className="p-6">
        <div className="flex items-center justify-between gap-4 mb-6 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="p-3 bg-[#ca8a04] rounded-2xl">
              <Rocket className="h-6 w-6 text-white" />
            </div>
            <div>
              <h2 className="text-2xl font-bold text-gray-900">
                {compact ? 'Suggested Next Steps' : 'Start Testing in 5 Minutes'}
              </h2>
              <p className="text-sm text-gray-600 mt-1">
                {compact
                  ? `${completedCount} of ${SETUP_STEPS.length} setup steps complete`
                  : 'Follow these quick steps to get started with voice AI testing'}
              </p>
            </div>
          </div>
          {!compact && (
            <Chip size="sm" className="bg-[#ca8a04] text-white font-semibold" radius="full">
              {completedCount}/{SETUP_STEPS.length} complete
            </Chip>
          )}
        </div>

        <div
          className={`grid gap-4 ${
            compact
              ? 'grid-cols-1 md:grid-cols-2'
              : 'grid-cols-1 md:grid-cols-2 lg:grid-cols-4'
          }`}
        >
          {stepsToShow.map((step) => {
            const done = setupProgress[step.key]
            const Icon = step.icon
            return (
              <Link key={step.key} to={step.href}>
                <Card
                  className={`h-full transition-all duration-200 hover:scale-[1.02] hover:shadow-md border-none ${
                    done ? 'bg-[#e6f4ea]/60' : 'bg-white/80 backdrop-blur-sm'
                  }`}
                  radius="lg"
                  isPressable
                >
                  <CardBody className="p-5">
                    <div className="flex items-start justify-between gap-2 mb-3">
                      <div className="w-10 h-10 rounded-xl bg-[#fef9c3] flex items-center justify-center flex-shrink-0">
                        <Icon className="h-5 w-5 text-[#ca8a04]" />
                      </div>
                      {done ? (
                        <CheckCircle2 className="w-5 h-5 text-[#137333] flex-shrink-0" />
                      ) : (
                        <Circle className="w-5 h-5 text-gray-300 flex-shrink-0" />
                      )}
                    </div>
                    <div className="flex items-center gap-2 mb-2">
                      <Chip size="sm" className="bg-[#ca8a04] text-white font-semibold" radius="full">
                        Step {step.step}
                      </Chip>
                      {done && (
                        <Chip size="sm" variant="flat" className="bg-[#e6f4ea] text-[#137333]" radius="full">
                          Done
                        </Chip>
                      )}
                    </div>
                    <h3 className="text-base font-semibold text-gray-900 mb-2">{step.title}</h3>
                    <p className="text-sm text-gray-600 mb-4">{step.description}</p>
                    {!done && (
                      <div className="flex items-center gap-1 text-sm font-medium text-[#a16207]">
                        Get started
                        <ArrowRight className="h-4 w-4" />
                      </div>
                    )}
                  </CardBody>
                </Card>
              </Link>
            )
          })}
        </div>
      </CardBody>
    </Card>
  )
}
