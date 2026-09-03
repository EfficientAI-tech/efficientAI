import { BrowserRouter, Routes, Route, Navigate, useParams, useLocation } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import { useLicenseStore } from './store/licenseStore'
import Layout from './components/Layout'

// Auth
import Login from './pages/auth/Login'
import InviteAccept from './pages/auth/InviteAccept'
import LoginCallback from './pages/auth/LoginCallback'
import SelectOrganization from './pages/auth/SelectOrganization'
import PlatformLogin from './pages/platform/PlatformLogin'
import PlatformAdmin from './pages/platform/PlatformAdmin'

// Dashboard
import Dashboard from './pages/dashboard/Dashboard'

// Usage
import UsagePage, { UsagePricingRedirect } from './pages/usage/UsagePage'

// Prompt Partials
import PromptPartials from './pages/promptPartials/PromptPartials'

// Agents
import AgentsWorkspace from './pages/agents/AgentsWorkspace'

// Personas
import Personas from './pages/personas/Personas'

// Scenarios
import Scenarios from './pages/scenarios/Scenarios'

// Metrics
import MetricsLayout from './pages/metrics/MetricsLayout'
import MetricsManagement from './pages/metrics/MetricsManagement'
import MetricsStudio from './pages/metrics/MetricsStudio'
import MetricsStudioRunDetail from './pages/metrics/MetricsStudioRunDetail'

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
import ResultsOverview from './pages/evaluators/results/ResultsOverview'
import ResultsAgentWorkspace from './pages/evaluators/results/ResultsAgentWorkspace'
import {
  RedirectAgentScenarioToWorkspace,
  RedirectAgentSuiteToWorkspace,
} from './pages/evaluators/results/ResultsAgentWorkspaceRedirects'
import ResultsUnassigned from './pages/evaluators/results/ResultsUnassigned'
import EvaluatorResultDetail from './pages/evaluators/results/EvaluatorResultDetail'
import EvaluationDetail from './pages/evaluators/results/EvaluationDetail'
import EvaluationsList from './pages/evaluators/results/EvaluationsList'

// Observability
import Observability from './pages/observability/Observability'
import ObservabilityCallDetail from './pages/observability/ObservabilityCallDetail'
import TestInsights from './pages/test-insights/TestInsights'
import CallTraceDetail from './pages/test-insights/CallTraceDetail'

// Alerting
import Alerts from './pages/alerting/Alerts'
import AlertDetail from './pages/alerting/AlertDetail'
import AlertHistory from './pages/alerting/AlertHistory'

// Configurations
import DataSources from './pages/configurations/DataSources'
import VoiceBundles from './pages/configurations/VoiceBundles'
import Integrations from './pages/configurations/Integrations'
import TelephonyNumbers from './pages/configurations/TelephonyNumbers'
import Settings from './pages/configurations/Settings'
import CronJobs from './pages/configurations/CronJobs'

// IAM
import IAM from './pages/iam/IAM'

// Profile
import Profile from './pages/profile/Profile'

// Prompt Optimization (Enterprise)
import PromptOptimization from './pages/promptOptimization/PromptOptimization'

// Judge Alignment (AlignEval-style hybrid integration)
import JudgeAlignment from './pages/judgeAlignment/JudgeAlignment'
import JudgeDatasetDetail from './pages/judgeAlignment/JudgeDatasetDetail'

// Enterprise
import EnterpriseUpgrade from './pages/enterprise/EnterpriseUpgrade'
import { WalkthroughProvider } from './context/WalkthroughContext'

// Public (no-auth) blind test form
import BlindTestForm from './pages/public/BlindTestForm'

// Call Imports
import CallImports from './pages/callImports/CallImports'
import CallImportDetail from './pages/callImports/CallImportDetail'
import CallImportEvaluationDetail from './pages/callImports/CallImportEvaluationDetail'
import CallImportTagsPage from './pages/callImports/Tags'
import CallImportSchemasPage from './pages/callImports/Schemas'


function PreserveSearchRedirect({ to }: { to: string }) {
  const location = useLocation()
  return <Navigate to={`${to}${location.search}`} replace />
}

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
        <Route path="/invite/:token" element={<InviteAccept />} />
        <Route path="/platform/login" element={<PlatformLogin />} />
        <Route path="/platform" element={<PlatformAdmin />} />
        <Route path="/login/callback" element={<LoginCallback />} />
        <Route path="/select-organization" element={<SelectOrganization />} />
        {/* Public blind test form - intentionally outside PrivateRoute and EnterpriseGate.
            Auth comes from the unguessable share token in the URL. */}
        <Route path="/blind-test/:token" element={<BlindTestForm />} />
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
          <Route path="evaluations" element={<EvaluationsList />} />
          <Route path="evaluations/:id" element={<EvaluationDetail />} />
          <Route path="playground" element={<AgentPlayground />} />
          <Route path="playground/call-recordings/:callShortId" element={<CallRecordingDetail />} />
          <Route path="playground/test-agent-results/:id" element={<TestAgentResultDetail />} />
          <Route path="agents" element={<AgentsWorkspace />} />
          <Route path="agents/:id" element={<AgentsWorkspace />} />
          <Route path="personas" element={<Personas />} />
          <Route path="scenarios" element={<Scenarios />} />
          <Route path="metrics" element={<Navigate to="/metrics-management/studio" replace />} />
          <Route path="integrations" element={<Integrations />} />
          <Route path="telephony-numbers" element={<TelephonyNumbers />} />
          <Route path="data-sources" element={<DataSources />} />
          <Route path="voicebundles" element={<VoiceBundles />} />
          <Route path="evaluate-test-agents" element={<EvaluateTestAgents />} />
          <Route path="evaluate-test-agents/:id" element={<EvaluatorDetail />} />
          <Route path="metrics-management" element={<MetricsLayout />}>
            <Route index element={<MetricsManagement />} />
            <Route path="studio" element={<MetricsStudio />} />
            <Route path="studio/runs/:runId" element={<MetricsStudioRunDetail />} />
          </Route>
          <Route path="results" element={<ResultsOverview />} />
          <Route path="results/unassigned" element={<ResultsUnassigned />} />
          <Route path="results/agents/:agentId" element={<ResultsAgentWorkspace />} />
          <Route
            path="results/agents/:agentId/suites/:suiteId"
            element={<RedirectAgentSuiteToWorkspace />}
          />
          <Route
            path="results/agents/:agentId/suites/:suiteId/scenarios/:scenarioId"
            element={<RedirectAgentScenarioToWorkspace />}
          />
          <Route path="results/:id" element={<EvaluatorResultDetail />} />
          <Route path="observability" element={<Observability />} />
          <Route path="observability/calls" element={<Navigate to="/calls" replace />} />
          <Route path="observability/calls/:callShortId" element={<ObservabilityCallDetail />} />
          <Route path="calls" element={<TestInsights />} />
          <Route path="calls/:traceId" element={<CallTraceDetail />} />
          <Route path="call-traces" element={<Navigate to="/calls" replace />} />
          <Route path="call-traces/:traceId" element={<CallTraceDetail />} />
          <Route path="test-insights" element={<PreserveSearchRedirect to="/calls" />} />
          <Route path="iam" element={<IAM />} />
          <Route path="usage" element={<UsagePage />} />
          <Route path="usage/pricing" element={<UsagePricingRedirect />} />
          <Route
            path="workspace-members"
            element={<Navigate to="/iam?tab=workspace-members" replace />}
          />
          <Route path="profile" element={<Profile />} />
          <Route path="settings" element={<Settings />} />
          <Route path="alerts" element={<Alerts />} />
          <Route path="alerts/:id" element={<AlertDetail />} />
          <Route path="alerts/history" element={<AlertHistory />} />
          <Route path="voice-playground" element={<EnterpriseGate feature="voice_playground"><VoicePlayground /></EnterpriseGate>} />
          <Route path="cron-jobs" element={<CronJobs />} />
          <Route path="prompt-partials" element={<PromptPartials />} />
          <Route path="prompt-partials/:id" element={<PromptPartials />} />
          <Route
            path="imported-agents"
            element={<Navigate to="/prompt-partials?kind=imported_agent" replace />}
          />
          <Route
            path="imported-agents/:id"
            element={<ImportedAgentRedirect />}
          />
          <Route path="call-imports" element={<EnterpriseGate feature="call_imports"><CallImports /></EnterpriseGate>} />
          <Route path="call-imports/tags" element={<EnterpriseGate feature="call_imports"><CallImportTagsPage /></EnterpriseGate>} />
          <Route path="call-imports/schemas" element={<EnterpriseGate feature="call_imports"><CallImportSchemasPage /></EnterpriseGate>} />
          <Route path="call-imports/:id" element={<EnterpriseGate feature="call_imports"><CallImportDetail /></EnterpriseGate>} />
          <Route
            path="call-imports/:id/evaluations/:evalId"
            element={<EnterpriseGate feature="call_imports"><CallImportEvaluationDetail /></EnterpriseGate>}
          />
          <Route path="prompt-optimization" element={<EnterpriseGate feature="gepa_optimization"><PromptOptimization /></EnterpriseGate>} />
          <Route path="judge-alignment" element={<JudgeAlignment />} />
          <Route path="judge-alignment/datasets/:datasetId" element={<JudgeDatasetDetail />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

function ImportedAgentRedirect() {
  const { id } = useParams<{ id: string }>()
  return (
    <Navigate to={`/prompt-partials/${id}?kind=imported_agent`} replace />
  )
}

export default App

