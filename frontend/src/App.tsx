import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Evaluations from './pages/Evaluations'
import EvaluationDetail from './pages/EvaluationDetail'
import BatchJobs from './pages/BatchJobs'
import BatchDetail from './pages/BatchDetail'
import ManualTranscriptionDetail from './pages/ManualTranscriptionDetail'
import Layout from './components/Layout'
import Agents from './pages/Agents'
import Personas from './pages/Personas'
import Scenarios from './pages/Scenarios'
import IAM from './pages/IAM'
import Profile from './pages/Profile'
import Metrics from './pages/Metrics'
import Integrations from './pages/Integrations'
import DataSources from './pages/DataSources'
import AIProviders from './pages/AIProviders'
import VoiceBundles from './pages/VoiceBundles'
import EvaluateTestAgents from './pages/EvaluateTestAgents'


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
          <Route path="evaluations" element={<Evaluations />} />
          <Route path="evaluations/:id" element={<EvaluationDetail />} />
          <Route path="manual-evaluations/:id" element={<ManualTranscriptionDetail />} />
          <Route path="batch" element={<BatchJobs />} />
          <Route path="batch/:id" element={<BatchDetail />} />
          <Route path="agents" element={<Agents />} />
          <Route path="personas" element={<Personas />} />
          <Route path="scenarios" element={<Scenarios />} />
          <Route path="metrics" element={<Metrics />} />
          <Route path="integrations" element={<Integrations />} />
          <Route path="data-sources" element={<DataSources />} />
          <Route path="ai-providers" element={<AIProviders />} />
          <Route path="voicebundles" element={<VoiceBundles />} />
          <Route path="evaluate-test-agents" element={<EvaluateTestAgents />} />
          <Route path="iam" element={<IAM />} />
          <Route path="profile" element={<Profile />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App

