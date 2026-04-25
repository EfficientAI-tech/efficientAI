export type WalkthroughSectionId =
  | 'integrations'
  | 'voicebundles'
  | 'agents'
  | 'personas'
  | 'scenarios'
  | 'evaluators'
  | 'voice-playground'
  | 'prompt-optimization'

export type ScenarioCreateMode = 'agent_prompt' | 'call' | 'custom' | null
export type EvaluatorCreateMode = 'standard' | 'custom'
export type VoicePlaygroundStep = 'configure' | 'progress' | 'results'
export type VoicePlaygroundTab = 'playground' | 'voices' | 'past-simulations'

export interface WalkthroughStep {
  title: string
  description: string
  bullets?: string[]
  ctaLabel?: string
  ctaPath?: string
}

export interface WalkthroughDefinition {
  id: WalkthroughSectionId
  title: string
  subtitle: string
  steps: WalkthroughStep[]
}

export interface ScenariosWalkthroughState {
  createMode?: ScenarioCreateMode
}

export interface EvaluatorsWalkthroughState {
  createMode?: EvaluatorCreateMode
  showCreateModal?: boolean
  showRunModal?: boolean
}

export interface VoicePlaygroundWalkthroughState {
  activeTab?: VoicePlaygroundTab
  step?: VoicePlaygroundStep
}

export interface PromptOptimizationWalkthroughState {
  hasSelectedRun?: boolean
  hasCompareCandidate?: boolean
  showNewRunDialog?: boolean
}

export type WalkthroughSectionStateMap = Partial<{
  scenarios: ScenariosWalkthroughState
  evaluators: EvaluatorsWalkthroughState
  'voice-playground': VoicePlaygroundWalkthroughState
  'prompt-optimization': PromptOptimizationWalkthroughState
}>

const walkthroughEnterpriseFeatures: Partial<Record<WalkthroughSectionId, string>> = {
  'voice-playground': 'voice_playground',
  'prompt-optimization': 'gepa_optimization',
}

const simpleWalkthroughs: Record<
  Exclude<WalkthroughSectionId, 'scenarios' | 'evaluators' | 'voice-playground' | 'prompt-optimization'>,
  WalkthroughDefinition
> = {
  integrations: {
    id: 'integrations',
    title: 'Integrations Walkthrough',
    subtitle: 'Connect voice platforms and LLM providers first.',
    steps: [
      {
        title: 'Step 1: Choose integration type',
        description: 'Pick Voice Platform or AI Provider from the Add Integration modal.',
        bullets: ['Voice Platform powers external call agents', 'AI Provider powers LLM-based generation and evaluation'],
      },
      {
        title: 'Step 2: Add credentials',
        description: 'Enter API keys for your provider and save the integration.',
        bullets: ['Vapi requires private + public keys', 'Platform and provider cannot be changed after creation'],
      },
      {
        title: 'Step 3: Verify configured integrations',
        description: 'Confirm your entries appear under Configured Integrations and are active.',
        bullets: ['Inactive integrations are not usable in downstream flows', 'Model and voice options depend on these being connected'],
      },
    ],
  },
  voicebundles: {
    id: 'voicebundles',
    title: 'Voice Bundle Walkthrough',
    subtitle: 'Define the speech + reasoning stack your agent uses.',
    steps: [
      {
        title: 'Step 1: Pick bundle type',
        description: 'Choose STT+LLM+TTS for a classic pipeline, or S2S for speech-to-speech.',
        bullets: ['S2S uses one model', 'STT+LLM+TTS exposes separate provider/model controls'],
      },
      {
        title: 'Step 2: Configure providers and models',
        description: 'Select provider + model per stage, then pick voice for TTS where available.',
        bullets: ['Missing STT/TTS models usually means provider capability mismatch', 'Provider options come from active integrations'],
      },
      {
        title: 'Step 3: Save and reuse',
        description: 'Create the VoiceBundle and attach it to agents and evaluator workflows.',
        bullets: ['Agents can be filtered by voice compatibility later', 'Voice Playground can reuse these defaults'],
      },
    ],
  },
  agents: {
    id: 'agents',
    title: 'Agents Walkthrough',
    subtitle: 'Create an agent with prompt, call mode, and external provider mapping.',
    steps: [
      {
        title: 'Step 1: Set call behavior',
        description: 'Choose Web Call or Phone Call, then choose Inbound or Outbound.',
        bullets: ['Phone Call requires a valid phone number', 'Language and call type should match your use case'],
      },
      {
        title: 'Step 2: Write the test agent prompt',
        description: 'Use AI Generate if needed, and optionally pull reusable text from Prompt Partials.',
        bullets: ['Minimum prompt length is enforced', 'Write/Preview modes help validate markdown formatting'],
      },
      {
        title: 'Step 3: Connect voice stack',
        description: 'Select a Voice Bundle and map the external voice provider agent ID.',
        bullets: ['Supported providers include Retell, Vapi, and ElevenLabs', 'Agent ID is required to connect external runtime behavior'],
      },
    ],
  },
  personas: {
    id: 'personas',
    title: 'Personas Walkthrough',
    subtitle: 'Create speaking profiles used during evaluations.',
    steps: [
      {
        title: 'Step 1: Create persona basics',
        description: 'Set persona name, gender, and TTS provider.',
        bullets: ['Provider choices come from configured voice integrations', 'Gender can auto-fill from selected voice'],
      },
      {
        title: 'Step 2: Pick a voice',
        description: 'Select a provider voice from the list and optionally filter by gender.',
        bullets: ['Voice inventory depends on provider + model availability', 'Persona voice selection affects evaluator compatibility'],
      },
      {
        title: 'Step 3: Add custom voices if needed',
        description: 'Use Custom Voices tab to register provider-specific voice IDs.',
        bullets: ['Custom voices become selectable in persona creation', 'You can edit and delete custom voices later'],
      },
    ],
  },
}

function getScenariosWalkthrough(state?: ScenariosWalkthroughState): WalkthroughDefinition {
  const mode = state?.createMode
  if (mode === 'agent_prompt') {
    return {
      id: 'scenarios',
      title: 'Scenarios Walkthrough',
      subtitle: 'Generate scenarios from the selected agent prompt.',
      steps: [
        {
          title: 'Step 1: Choose generation source',
          description: 'Select an agent with a strong system prompt and pick scenario count.',
          bullets: ['Count supports 1-10 drafts', 'Agent prompt quality directly impacts output quality'],
        },
        {
          title: 'Step 2: Select AI provider + model',
          description: 'Pick LLM provider and model used for scenario generation.',
          bullets: ['Provider/model must be configured in Integrations', 'Optional context can focus generation on edge cases'],
        },
        {
          title: 'Step 3: Review and save drafts',
          description: 'Edit generated draft names/descriptions and save selected scenarios.',
          bullets: ['Each draft can be saved independently', 'Saved scenarios can be linked to evaluators later'],
        },
      ],
    }
  }

  if (mode === 'call') {
    return {
      id: 'scenarios',
      title: 'Scenarios Walkthrough',
      subtitle: 'Create scenarios from call transcript or call data.',
      steps: [
        {
          title: 'Step 1: Paste call data',
          description: 'Use transcript text or call details in Generate from Call mode.',
          bullets: ['Keep input clean and complete for better extraction', 'Current flow creates a basic scenario structure'],
        },
        {
          title: 'Step 2: Generate scenario',
          description: 'Run generation and review the generated scenario description.',
          bullets: ['Use this to turn real interactions into test cases', 'Iterate with cleaner transcripts when needed'],
        },
      ],
    }
  }

  if (mode === 'custom') {
    return {
      id: 'scenarios',
      title: 'Scenarios Walkthrough',
      subtitle: 'Manually define custom test scenarios.',
      steps: [
        {
          title: 'Step 1: Enter scenario details',
          description: 'Provide scenario name and optional linked agent.',
          bullets: ['Linking an agent can improve traceability', 'Descriptions should be specific and test-oriented'],
        },
        {
          title: 'Step 2: Save scenario',
          description: 'Create the scenario and verify it appears in Your Scenarios.',
          bullets: ['Scenarios can be edited later', 'Manual scenarios are best for strict QA scripts'],
        },
      ],
    }
  }

  return {
    id: 'scenarios',
    title: 'Scenarios Walkthrough',
    subtitle: 'Choose one of three scenario creation modes.',
    steps: [
      {
        title: 'Step 1: Pick creation mode',
        description: 'Choose Generate from Agent Prompt, Generate from Call, or Create Manually.',
        bullets: ['Agent Prompt mode is fastest for multiple drafts', 'Manual mode gives full control'],
      },
      {
        title: 'Step 2: Create and refine',
        description: 'Generate or author scenarios, then edit names and descriptions before use.',
        bullets: ['Keep scenarios focused on one user intent each', 'Link to agents where useful'],
      },
      {
        title: 'Step 3: Use in evaluators',
        description: 'Select these scenarios when building evaluators for batch runs.',
      },
    ],
  }
}

function getEvaluatorsWalkthrough(state?: EvaluatorsWalkthroughState): WalkthroughDefinition {
  if (state?.showRunModal) {
    return {
      id: 'evaluators',
      title: 'Evaluators Walkthrough',
      subtitle: 'You are in run configuration mode.',
      steps: [
        {
          title: 'Step 1: Confirm selected evaluators',
          description: 'Review how many evaluator rows are selected in the run modal.',
        },
        {
          title: 'Step 2: Set run count',
          description: 'Choose how many times each evaluator should run.',
          bullets: ['Higher counts increase confidence in consistency', 'Total queued jobs = selected evaluators x run count'],
        },
        {
          title: 'Step 3: Queue runs',
          description: 'Start the run and monitor background progress from results.',
        },
      ],
    }
  }

  if (state?.showCreateModal && state?.createMode === 'custom') {
    return {
      id: 'evaluators',
      title: 'Evaluators Walkthrough',
      subtitle: 'Create custom prompt evaluators for external recordings.',
      steps: [
        {
          title: 'Step 1: Name evaluator + add prompt',
          description: 'Provide evaluator name and paste full agent prompt/instructions.',
          bullets: ['Format with AI can structure long prompts', 'Detailed prompts improve evaluation relevance'],
        },
        {
          title: 'Step 2: Select evaluation model',
          description: 'Choose LLM provider/model for transcript evaluation.',
          bullets: ['Defaults are used if no provider is configured', 'Model choice affects scoring quality and cost'],
        },
        {
          title: 'Step 3: Create evaluator',
          description: 'Save custom evaluator and run it against recordings from the table.',
        },
      ],
    }
  }

  if (state?.showCreateModal) {
    return {
      id: 'evaluators',
      title: 'Evaluators Walkthrough',
      subtitle: 'Create standard evaluators from agent + persona + scenario.',
      steps: [
        {
          title: 'Step 1: Select agent and scenario',
          description: 'Pick the target agent and scenario to evaluate.',
          bullets: ['Scenario should match expected call behavior', 'Evaluator name is optional but recommended'],
        },
        {
          title: 'Step 2: Select personas',
          description: 'Choose one or more personas compatible with the agent voice bundle.',
          bullets: ['Incompatible personas may be hidden', 'Each persona creates its own evaluator variant'],
        },
        {
          title: 'Step 3: Save and run',
          description: 'Create evaluator rows, select them via checkbox, then click Run.',
        },
      ],
    }
  }

  return {
    id: 'evaluators',
    title: 'Evaluators Walkthrough',
    subtitle: 'Create evaluator configs and run them in batches.',
    steps: [
      {
        title: 'Step 1: Create evaluator',
        description: 'Use Create Evaluator to add standard or custom prompt evaluators.',
      },
      {
        title: 'Step 2: Select rows',
        description: 'Use checkboxes to choose evaluators for run or bulk delete.',
      },
      {
        title: 'Step 3: Run in background',
        description: 'Open Run modal, set run count, and queue jobs.',
        bullets: ['Progress appears in results views', 'First-time metric model downloads can be slower'],
      },
    ],
  }
}

function getVoicePlaygroundWalkthrough(state?: VoicePlaygroundWalkthroughState): WalkthroughDefinition {
  if (state?.activeTab === 'voices') {
    return {
      id: 'voice-playground',
      title: 'Voice Playground Walkthrough',
      subtitle: 'Manage custom voices for benchmark runs.',
      steps: [
        {
          title: 'Step 1: Add custom voices',
          description: 'Register provider-specific voice IDs in the Voices tab.',
        },
        {
          title: 'Step 2: Reuse in comparisons',
          description: 'Custom voices appear in provider voice selectors for benchmarks.',
        },
      ],
    }
  }

  if (state?.activeTab === 'past-simulations') {
    return {
      id: 'voice-playground',
      title: 'Voice Playground Walkthrough',
      subtitle: 'Review past simulations and analytics.',
      steps: [
        {
          title: 'Step 1: Open a simulation',
          description: 'Review side A/B outputs, metrics, and generated artifacts.',
        },
        {
          title: 'Step 2: Compare performance trends',
          description: 'Use analytics to identify provider/model/voice trends over time.',
        },
      ],
    }
  }

  if (state?.step === 'progress') {
    return {
      id: 'voice-playground',
      title: 'Voice Playground Walkthrough',
      subtitle: 'Benchmark is running.',
      steps: [
        {
          title: 'Step 1: Track generation and evaluation',
          description: 'Watch progress through generating and evaluating samples.',
        },
        {
          title: 'Step 2: Wait for audio',
          description:
            'Once audio clips are ready you jump straight to results — evaluation metrics keep computing in the background.',
        },
      ],
    }
  }

  if (state?.step === 'results') {
    return {
      id: 'voice-playground',
      title: 'Voice Playground Walkthrough',
      subtitle: 'Analyze benchmark outputs.',
      steps: [
        {
          title: 'Step 1: Review scores and samples',
          description: 'Inspect metrics and listen to generated audio samples.',
        },
        {
          title: 'Step 2: Export report',
          description: 'Download or generate report artifacts for sharing.',
        },
        {
          title: 'Step 3: Create blind test',
          description:
            'Use "Create Blind Test" to generate a public link for raters to score voices — works as soon as audio is ready, even while evaluation is still running.',
          bullets: [
            'Add custom rating metrics (e.g. naturalness, clarity)',
            'Close the form when you have enough responses',
            'External responses merge into the same evaluation summary',
            'Each email can only respond once per blind test',
          ],
        },
        {
          title: 'Step 4: Run next comparison',
          description: 'Reset and iterate with different providers/models/voices.',
        },
      ],
    }
  }

  return {
    id: 'voice-playground',
    title: 'Voice Playground Walkthrough',
    subtitle: 'Configure benchmark setup before running.',
    steps: [
      {
        title: 'Step 1: Add prompt samples',
        description: 'Use default prompts, custom text, or AI-generated text samples.',
        bullets: ['You can save generated prompts to Prompt Partials'],
      },
      {
        title: 'Step 2: Set benchmark configuration',
        description: 'Select providers, models, voices, sample rates, and run count.',
        bullets: ['Enable comparison for A/B mode', 'Choose evaluation STT for WER/CER metrics'],
      },
      {
        title: 'Step 3: Run benchmark',
        description: 'Start benchmark and follow progress into blind-test and results steps.',
      },
    ],
  }
}

function getPromptOptimizationWalkthrough(
  state?: PromptOptimizationWalkthroughState
): WalkthroughDefinition {
  if (state?.showNewRunDialog) {
    return {
      id: 'prompt-optimization',
      title: 'Prompt Optimization Walkthrough',
      subtitle: 'Configure a new optimization run.',
      steps: [
        {
          title: 'Step 1: Select agent (and evaluator optionally)',
          description: 'Choose target agent prompt and optional evaluator context.',
        },
        {
          title: 'Step 2: Set optimization budget',
          description: 'Tune max metric calls and minibatch size.',
          bullets: ['Higher budgets improve exploration', 'Minibatch controls examples per iteration'],
        },
        {
          title: 'Step 3: Start run',
          description: 'Launch optimization and monitor candidate generation in the run list.',
        },
      ],
    }
  }

  if (!state?.hasSelectedRun) {
    return {
      id: 'prompt-optimization',
      title: 'Prompt Optimization Walkthrough',
      subtitle: 'Start by selecting or creating a run.',
      steps: [
        {
          title: 'Step 1: Create a run',
          description: 'Open New Run and choose the target agent prompt to optimize.',
        },
        {
          title: 'Step 2: Wait for candidates',
          description: 'Optimization runs asynchronously and generates scored candidates.',
        },
        {
          title: 'Step 3: Select a run from the left list',
          description: 'Open run details to compare seed and optimized prompts.',
        },
      ],
    }
  }

  if (state?.hasCompareCandidate) {
    return {
      id: 'prompt-optimization',
      title: 'Prompt Optimization Walkthrough',
      subtitle: 'Compare seed prompt versus optimized candidate.',
      steps: [
        {
          title: 'Step 1: Compare prompts side-by-side',
          description: 'Review candidate quality and score against the original prompt.',
        },
        {
          title: 'Step 2: Accept best candidate',
          description: 'Mark one candidate as accepted for deployment.',
        },
        {
          title: 'Step 3: Push to provider',
          description: 'Push accepted prompt to connected external provider and sync agent prompt.',
        },
      ],
    }
  }

  return {
    id: 'prompt-optimization',
    title: 'Prompt Optimization Walkthrough',
    subtitle: 'Run, inspect, and deploy optimized prompts.',
    steps: [
      {
        title: 'Step 1: Open run details',
        description: 'Select a run from the left sidebar to view score and progression.',
      },
      {
        title: 'Step 2: Inspect candidates',
        description: 'Open candidate cards to evaluate generated prompt variants.',
      },
      {
        title: 'Step 3: Accept and push',
        description: 'Accept a candidate then push it to your voice provider when ready.',
      },
    ],
  }
}

export function getWalkthroughSectionId(pathname: string): WalkthroughSectionId | null {
  if (pathname.startsWith('/integrations')) return 'integrations'
  if (pathname.startsWith('/voicebundles')) return 'voicebundles'
  if (pathname.startsWith('/agents')) return 'agents'
  if (pathname.startsWith('/personas')) return 'personas'
  if (pathname.startsWith('/scenarios')) return 'scenarios'
  if (pathname.startsWith('/evaluate-test-agents')) return 'evaluators'
  if (pathname.startsWith('/voice-playground')) return 'voice-playground'
  if (pathname.startsWith('/prompt-optimization')) return 'prompt-optimization'
  return null
}

export function getWalkthroughDefinition(
  sectionId: WalkthroughSectionId,
  state: WalkthroughSectionStateMap
): WalkthroughDefinition {
  switch (sectionId) {
    case 'scenarios':
      return getScenariosWalkthrough(state.scenarios)
    case 'evaluators':
      return getEvaluatorsWalkthrough(state.evaluators)
    case 'voice-playground':
      return getVoicePlaygroundWalkthrough(state['voice-playground'])
    case 'prompt-optimization':
      return getPromptOptimizationWalkthrough(state['prompt-optimization'])
    default:
      return simpleWalkthroughs[sectionId]
  }
}

export function getWalkthroughEnterpriseFeature(sectionId: WalkthroughSectionId): string | null {
  return walkthroughEnterpriseFeatures[sectionId] ?? null
}
