import { useState, useEffect } from 'react'
import { Users, Volume2, Globe, User } from 'lucide-react'
import { apiClient } from '../lib/api'

interface Persona {
  id: string
  name: string
  language: string
  accent: string
  gender: string
  background_noise: string
  created_at: string
  updated_at: string
}

const genderIcons: Record<string, string> = {
  male: '👨',
  female: '👩',
  neutral: '🧑'
}

const accentFlags: Record<string, string> = {
  american: '🇺🇸',
  british: '🇬🇧',
  australian: '🇦🇺',
  indian: '🇮🇳',
  chinese: '🇨🇳',
  spanish: '🇪🇸',
  french: '🇫🇷',
  german: '🇩🇪',
  neutral: '🌍'
}

export default function Personas() {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchPersonas()
  }, [])

  const fetchPersonas = async () => {
    try {
      const data = await apiClient.listPersonas()
      setPersonas(data)
    } catch (error) {
      console.error('Error fetching personas:', error)
    } finally {
      setLoading(false)
    }
  }

  const seedDemoData = async () => {
    try {
      await apiClient.seedDemoData()
      fetchPersonas()
    } catch (error) {
      console.error('Error seeding data:', error)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Loading personas...</div>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Test Personas</h1>
          <p className="text-gray-600 mt-1">Pre-built personas for testing voice AI agents</p>
        </div>
        {personas.length === 0 && (
          <button
            onClick={seedDemoData}
            className="bg-primary-600 text-white px-4 py-2 rounded-lg hover:bg-primary-700 transition-colors"
          >
            Load Demo Personas
          </button>
        )}
      </div>

      {personas.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <Users className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No personas yet</h3>
          <p className="text-gray-500 mb-4">Load demo personas to get started with testing</p>
          <button
            onClick={seedDemoData}
            className="text-primary-600 hover:text-primary-700 font-medium"
          >
            Load demo personas →
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {personas.map((persona) => (
            <div
              key={persona.id}
              className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition-shadow border border-gray-100"
            >
              <div className="flex items-start justify-between mb-4">
                <div className="text-4xl">{genderIcons[persona.gender] || '🧑'}</div>
                <div className="text-2xl">{accentFlags[persona.accent] || '🌍'}</div>
              </div>

              <h3 className="text-lg font-bold text-gray-900 mb-2">{persona.name}</h3>

              <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm text-gray-600">
                  <User className="w-4 h-4 text-gray-400" />
                  <span className="capitalize">{persona.gender}</span>
                </div>

                <div className="flex items-center gap-2 text-sm text-gray-600">
                  <Globe className="w-4 h-4 text-gray-400" />
                  <span className="capitalize">{persona.accent} accent</span>
                </div>

                <div className="flex items-center gap-2 text-sm text-gray-600">
                  <Volume2 className="w-4 h-4 text-gray-400" />
                  <span className="capitalize">
                    {persona.background_noise === 'none' ? 'No background noise' : `${persona.background_noise} noise`}
                  </span>
                </div>
              </div>

              <div className="mt-4 pt-4 border-t border-gray-100">
                <button className="w-full text-center text-sm text-primary-600 hover:text-primary-700 font-medium">
                  Use in Test →
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {personas.length > 0 && (
        <div className="mt-6 p-4 bg-orange-50 rounded-lg border border-orange-100">
          <p className="text-sm text-orange-800">
            💡 <strong>Tip:</strong> These personas simulate different caller types. Use them to test how your agent handles various customer behaviors and environments.
          </p>
        </div>
      )}
    </div>
  )
}