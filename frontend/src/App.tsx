import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import { useLicenseStore } from './store/licenseStore'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import EvaluationDetail from './pages/EvaluationDetail'
import Playground from './components/Playground'
import Layout from './components/Layout'
import Agents from './pages/Agents'
import Personas from './pages/Personas'
import Scenarios from './pages/Scenarios'
import IAM from './pages/IAM'
import Profile from './pages/Profile'
import Metrics from './pages/Metrics'
import Integrations from './pages/Integrations'
import DataSources from './pages/DataSources'
import VoiceBundles from './pages/VoiceBundles'
import EvaluateTestAgents from './pages/EvaluateTestAgents'
import EvaluatorDetail from './pages/EvaluatorDetail'
import MetricsManagement from './pages/MetricsManagement'
import Results from './pages/Results'
import EvaluatorResultDetail from './pages/EvaluatorResultDetail'
import AgentDetail from './pages/AgentDetail'
import Observability from './pages/Observability'
import ObservabilityCalls from './pages/ObservabilityCalls'
import ObservabilityCallDetail from './pages/ObservabilityCallDetail'
import CallRecordingDetail from './pages/CallRecordingDetail'
import TestAgentResultDetail from './pages/TestAgentResultDetail'
import Settings from './pages/Settings'
import Alerts from './pages/Alerts'
import AlertDetail from './pages/AlertDetail'
import AlertHistory from './pages/AlertHistory'
import CronJobs from './pages/CronJobs'
import VoicePlayground from './pages/VoicePlayground'
import EnterpriseUpgrade from './pages/EnterpriseUpgrade'


function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { apiKey } = useAuthStore()
  
  if (!apiKey) {
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
              <Layout />
            </PrivateRoute>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="evaluations/:id" element={<EvaluationDetail />} />
          <Route path="playground" element={<Playground />} />
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
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App

