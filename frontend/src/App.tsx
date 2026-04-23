import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import { useLicenseStore } from './store/licenseStore'
import Layout from './components/Layout'

// Auth
import Login from './pages/auth/Login'

// Dashboard
import Dashboard from './pages/dashboard/Dashboard'

// Prompt Partials
import PromptPartials from './pages/promptPartials/PromptPartials'

// Agents
import Agents from './pages/agents/Agents'
import AgentDetail from './pages/agents/AgentDetail'

// Personas
import Personas from './pages/personas/Personas'

// Scenarios
import Scenarios from './pages/scenarios/Scenarios'

// Metrics
import Metrics from './pages/metrics/Metrics'
import MetricsManagement from './pages/metrics/MetricsManagement'

// Playground - Agent
import AgentPlayground from './pages/playground/agent/AgentPlayground'
import CallRecordingDetail from './pages/playground/agent/CallRecordingDetail'
import TestAgentResultDetail from './pages/playground/agent/TestAgentResultDetail'

// Playground - Voice
import VoicePlayground from './pages/playground/voice/VoicePlayground'

// Evaluators
import EvaluateTestAgents from './pages/evaluators/evaluators/EvaluateTestAgents'
import EvaluatorDetail from './pages/evaluators/evaluators/EvaluatorDetail'

// Evaluator Results
import Results from './pages/evaluators/results/Results'
import EvaluatorResultDetail from './pages/evaluators/results/EvaluatorResultDetail'
import EvaluationDetail from './pages/evaluators/results/EvaluationDetail'

// Observability
import Observability from './pages/observability/Observability'
import ObservabilityCalls from './pages/observability/ObservabilityCalls'
import ObservabilityCallDetail from './pages/observability/ObservabilityCallDetail'

// Alerting
import Alerts from './pages/alerting/Alerts'
import AlertDetail from './pages/alerting/AlertDetail'
import AlertHistory from './pages/alerting/AlertHistory'

// Configurations
import DataSources from './pages/configurations/DataSources'
import VoiceBundles from './pages/configurations/VoiceBundles'
import Integrations from './pages/configurations/Integrations'
import Settings from './pages/configurations/Settings'
import CronJobs from './pages/configurations/CronJobs'

// IAM
import IAM from './pages/iam/IAM'

// Profile
import Profile from './pages/profile/Profile'

// Prompt Optimization (Enterprise)
import PromptOptimization from './pages/promptOptimization/PromptOptimization'

// Enterprise
import EnterpriseUpgrade from './pages/enterprise/EnterpriseUpgrade'
import { WalkthroughProvider } from './context/WalkthroughContext'


function PrivateRoute({ children }: { children: React.ReactNode }) {
  // Either credential type counts as "signed in". The backend enforces the
  // actual authentication on every request; this guard just keeps the SPA
  // from flashing protected pages when the user clearly has no session.
  const { apiKey, accessToken } = useAuthStore()

  if (!apiKey && !accessToken) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

function EnterpriseGate({ feature, children }: { feature: string; children: React.ReactNode }) {
  const { isFeatureEnabled, isLoaded } = useLicenseStore()

  if (!isLoaded) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900" />
      </div>
    )
  }

  if (!isFeatureEnabled(feature)) {
    return <EnterpriseUpgrade feature={feature} />
  }

  return <>{children}</>
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <PrivateRoute>
              <WalkthroughProvider>
                <Layout />
              </WalkthroughProvider>
            </PrivateRoute>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="evaluations/:id" element={<EvaluationDetail />} />
          <Route path="playground" element={<AgentPlayground />} />
          <Route path="playground/call-recordings/:callShortId" element={<CallRecordingDetail />} />
          <Route path="playground/test-agent-results/:id" element={<TestAgentResultDetail />} />
          <Route path="agents" element={<Agents />} />
          <Route path="agents/:id" element={<AgentDetail />} />
          <Route path="personas" element={<Personas />} />
          <Route path="scenarios" element={<Scenarios />} />
          <Route path="metrics" element={<Metrics />} />
          <Route path="integrations" element={<Integrations />} />
          <Route path="data-sources" element={<DataSources />} />
          <Route path="voicebundles" element={<VoiceBundles />} />
          <Route path="evaluate-test-agents" element={<EvaluateTestAgents />} />
          <Route path="evaluate-test-agents/:id" element={<EvaluatorDetail />} />
          <Route path="metrics-management" element={<MetricsManagement />} />
          <Route path="results" element={<Results />} />
          <Route path="results/:id" element={<EvaluatorResultDetail />} />
          <Route path="observability" element={<Observability />} />
          <Route path="observability/calls" element={<ObservabilityCalls />} />
          <Route path="observability/calls/:callShortId" element={<ObservabilityCallDetail />} />
          <Route path="iam" element={<IAM />} />
          <Route path="profile" element={<Profile />} />
          <Route path="settings" element={<Settings />} />
          <Route path="alerts" element={<Alerts />} />
          <Route path="alerts/:id" element={<AlertDetail />} />
          <Route path="alerts/history" element={<AlertHistory />} />
          <Route path="voice-playground" element={<EnterpriseGate feature="voice_playground"><VoicePlayground /></EnterpriseGate>} />
          <Route path="cron-jobs" element={<CronJobs />} />
          <Route path="prompt-partials" element={<PromptPartials />} />
          <Route path="prompt-optimization" element={<EnterpriseGate feature="gepa_optimization"><PromptOptimization /></EnterpriseGate>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App

