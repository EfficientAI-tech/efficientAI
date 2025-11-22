import { useState } from 'react'
import ManualEvaluations from '../components/ManualEvaluations'
import ManualEvaluationsList from '../components/ManualEvaluationsList'

export default function Evaluations() {
  const [showTranscriptionForm, setShowTranscriptionForm] = useState(false)

  return (
    <div className="space-y-6">
      {showTranscriptionForm ? (
        <ManualEvaluations onBack={() => setShowTranscriptionForm(false)} />
      ) : (
        <ManualEvaluationsList onNewTranscription={() => setShowTranscriptionForm(true)} />
      )}
    </div>
  )
}
