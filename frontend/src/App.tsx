import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import AudioFiles from './pages/AudioFiles'
import Evaluations from './pages/Evaluations'
import EvaluationDetail from './pages/EvaluationDetail'
import BatchJobs from './pages/BatchJobs'
import BatchDetail from './pages/BatchDetail'
import Layout from './components/Layout'
import Agents from './pages/Agents'
import Personas from './pages/Personas'
import Scenarios from './pages/Scenarios'


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
          <Route path="audio" element={<AudioFiles />} />
          <Route path="evaluations" element={<Evaluations />} />
          <Route path="evaluations/:id" element={<EvaluationDetail />} />
          <Route path="batch" element={<BatchJobs />} />
          <Route path="batch/:id" element={<BatchDetail />} />
          <Route path="agents" element={<Agents />} />
          <Route path="personas" element={<Personas />} />
          <Route path="scenarios" element={<Scenarios />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App

