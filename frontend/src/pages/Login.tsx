import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { apiClient } from '../lib/api'
import { AlertCircle } from 'lucide-react'
import Logo from '../components/Logo'

export default function Login() {
  const navigate = useNavigate()
  const { setApiKey } = useAuthStore()
  const [apiKey, setApiKeyValue] = useState('')
  const [keyName, setKeyName] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [showGenerate, setShowGenerate] = useState(false)
  const [generatedKey, setGeneratedKey] = useState('')

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      // Validate the API key by trying to use it
      apiClient.setApiKey(apiKey)
      const result = await apiClient.validateApiKey()
      
      if (result.valid) {
        setApiKey(apiKey)
        navigate('/')
      } else {
        setError('Invalid API key')
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to validate API key')
    } finally {
      setIsLoading(false)
    }
  }

  const handleGenerateKey = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      const result = await apiClient.generateApiKey(keyName || undefined)
      setGeneratedKey(result.key)
      setShowGenerate(true)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to generate API key')
    } finally {
      setIsLoading(false)
    }
  }

  const handleUseGeneratedKey = () => {
    setApiKey(generatedKey)
    navigate('/')
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-primary-50 to-primary-100 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        <div className="text-center">
          <div className="flex justify-center mb-4">
            <Logo textSize="xl" />
          </div>
          <p className="mt-2 text-sm text-gray-600">
            Sign in with your API key to continue
          </p>
        </div>

        <div className="bg-white py-8 px-6 shadow-xl rounded-lg">
          {!showGenerate ? (
            <>
              <form onSubmit={handleLogin} className="space-y-6">
                <div>
                  <label htmlFor="apiKey" className="block text-sm font-medium text-gray-700">
                    API Key
                  </label>
                  <input
                    id="apiKey"
                    name="apiKey"
                    type="text"
                    required
                    value={apiKey}
                    onChange={(e) => setApiKeyValue(e.target.value)}
                    className="mt-1 appearance-none relative block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-md focus:outline-none focus:ring-primary-500 focus:border-primary-500 focus:z-10 sm:text-sm"
                    placeholder="Enter your API key"
                  />
                </div>

                {error && (
                  <div className="rounded-md bg-red-50 p-4">
                    <div className="flex">
                      <AlertCircle className="h-5 w-5 text-red-400" />
                      <div className="ml-3">
                        <p className="text-sm text-red-800">{error}</p>
                      </div>
                    </div>
                  </div>
                )}

                <div>
                  <button
                    type="submit"
                    disabled={isLoading}
                    className="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 disabled:opacity-50"
                  >
                    {isLoading ? 'Signing in...' : 'Sign in'}
                  </button>
                </div>
              </form>

              <div className="mt-6">
                <div className="relative">
                  <div className="absolute inset-0 flex items-center">
                    <div className="w-full border-t border-gray-300" />
                  </div>
                  <div className="relative flex justify-center text-sm">
                    <span className="px-2 bg-white text-gray-500">Or</span>
                  </div>
                </div>

                <div className="mt-6">
                  <button
                    onClick={() => setShowGenerate(true)}
                    className="w-full flex justify-center py-2 px-4 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50"
                  >
                    Generate New API Key
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className="space-y-6">
              <div>
                <label htmlFor="keyName" className="block text-sm font-medium text-gray-700">
                  Key Name (optional)
                </label>
                <input
                  id="keyName"
                  name="keyName"
                  type="text"
                  value={keyName}
                  onChange={(e) => setKeyName(e.target.value)}
                  className="mt-1 appearance-none relative block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-md focus:outline-none focus:ring-primary-500 focus:border-primary-500 sm:text-sm"
                  placeholder="e.g., My Development Key"
                />
              </div>

              <button
                onClick={handleGenerateKey}
                disabled={isLoading}
                className="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 disabled:opacity-50"
              >
                {isLoading ? 'Generating...' : 'Generate API Key'}
              </button>

              {generatedKey && (
                <div className="rounded-md bg-green-50 p-4">
                  <p className="text-sm font-medium text-green-800 mb-2">
                    API Key generated successfully!
                  </p>
                  <div className="bg-white p-3 rounded border border-green-200">
                    <code className="text-xs text-gray-900 break-all">{generatedKey}</code>
                  </div>
                  <p className="mt-2 text-xs text-green-700">
                    Please save this key securely. You won't be able to see it again.
                  </p>
                  <button
                    onClick={handleUseGeneratedKey}
                    className="mt-3 w-full py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-green-600 hover:bg-green-700"
                  >
                    Use This Key to Sign In
                  </button>
                </div>
              )}

              {error && (
                <div className="rounded-md bg-red-50 p-4">
                  <p className="text-sm text-red-800">{error}</p>
                </div>
              )}

              <button
                onClick={() => {
                  setShowGenerate(false)
                  setGeneratedKey('')
                  setError('')
                }}
                className="w-full text-sm text-gray-600 hover:text-gray-900"
              >
                ← Back to sign in
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

