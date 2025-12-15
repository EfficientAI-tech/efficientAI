import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
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
import MetricsManagement from './pages/MetricsManagement'
import Results from './pages/Results'
import EvaluatorResultDetail from './pages/EvaluatorResultDetail'
import AgentDetail from './pages/AgentDetail'
import Observability from './pages/Observability'
import CallRecordingDetail from './pages/CallRecordingDetail'


function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { apiKey } = useAuthStore()
  
  if (!apiKey) {
    return <Navigate to="/login" replace />
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
          <Route path="agents" element={<Agents />} />
          <Route path="agents/:id" element={<AgentDetail />} />
          <Route path="personas" element={<Personas />} />
          <Route path="scenarios" element={<Scenarios />} />
          <Route path="metrics" element={<Metrics />} />
          <Route path="integrations" element={<Integrations />} />
          <Route path="data-sources" element={<DataSources />} />
          <Route path="voicebundles" element={<VoiceBundles />} />
          <Route path="evaluate-test-agents" element={<EvaluateTestAgents />} />
          <Route path="metrics-management" element={<MetricsManagement />} />
          <Route path="results" element={<Results />} />
          <Route path="results/:id" element={<EvaluatorResultDetail />} />
          <Route path="observability" element={<Observability />} />
          <Route path="iam" element={<IAM />} />
          <Route path="profile" element={<Profile />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App

