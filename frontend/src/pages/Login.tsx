import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { apiClient } from '../lib/api'
import { AlertCircle, ArrowLeft, CheckCircle2, Copy } from 'lucide-react'
import Logo from '../components/Logo'
import {
  Card,
  CardBody,
  Button,
  Divider,
  Snippet,
  Chip,
} from '@heroui/react'

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

  const handleGenerateKey = async () => {
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
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-amber-50 via-yellow-50 to-orange-50 py-12 px-4 sm:px-6 lg:px-8">
      {/* Background decoration */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-primary-200 rounded-full mix-blend-multiply filter blur-xl opacity-30 animate-pulse" />
        <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-orange-200 rounded-full mix-blend-multiply filter blur-xl opacity-30 animate-pulse" />
      </div>

      <div className="max-w-md w-full space-y-8 relative z-10">
        <div className="text-center">
          <div className="flex justify-center mb-4">
            <Logo textSize="xl" />
          </div>
          <p className="mt-2 text-sm text-gray-600">
            Sign in with your API key to continue
          </p>
        </div>

        <Card className="shadow-xl">
          <CardBody className="p-8">
            {!showGenerate ? (
              <>
                <form onSubmit={handleLogin} className="space-y-6">
                  <input
                    type="text"
                    placeholder="Enter your API key"
                    value={apiKey}
                    onChange={(e) => setApiKeyValue(e.target.value)}
                    required
                    className="w-full px-5 py-4 text-base text-gray-900 bg-gray-50 border-2 border-gray-200 rounded-full focus:outline-none focus:border-[#ca8a04] focus:bg-white transition-all duration-200 placeholder:text-gray-400"
                  />

                  {error && (
                    <Chip
                      color="danger"
                      variant="flat"
                      startContent={<AlertCircle className="w-4 h-4" />}
                      className="w-full max-w-full h-auto py-2"
                    >
                      {error}
                    </Chip>
                  )}

                  <Button
                    type="submit"
                    color="primary"
                    isLoading={isLoading}
                    className="w-full font-semibold bg-[#fef9c3] hover:bg-[#fef08a] text-[#a16207] border border-[#facc15]"
                    size="lg"
                    radius="full"
                  >
                    Sign in
                  </Button>
                </form>

                <div className="my-6">
                  <Divider />
                  <p className="text-center text-sm text-gray-500 -mt-3 bg-white px-2 mx-auto w-fit">
                    Or
                  </p>
                </div>

                <Button
                  variant="bordered"
                  onPress={() => setShowGenerate(true)}
                  className="w-full border-2 border-[#dadce0] text-gray-700 hover:bg-gray-50"
                  size="lg"
                  radius="full"
                >
                  Generate New API Key
                </Button>
              </>
            ) : (
              <div className="space-y-6">
                <input
                  type="text"
                  placeholder="Key name (optional)"
                  value={keyName}
                  onChange={(e) => setKeyName(e.target.value)}
                  className="w-full px-5 py-4 text-base text-gray-900 bg-gray-50 border-2 border-gray-200 rounded-full focus:outline-none focus:border-[#ca8a04] focus:bg-white transition-all duration-200 placeholder:text-gray-400"
                />

                <Button
                  color="primary"
                  onPress={handleGenerateKey}
                  isLoading={isLoading}
                  className="w-full font-semibold bg-[#fef9c3] hover:bg-[#fef08a] text-[#a16207]"
                  size="lg"
                  radius="full"
                >
                  Generate API Key
                </Button>

                {generatedKey && (
                  <Card className="bg-[#e6f4ea] border border-[#ceead6]" radius="lg">
                    <CardBody className="p-4 space-y-3">
                      <div className="flex items-center gap-2 text-[#137333]">
                        <CheckCircle2 className="w-5 h-5" />
                        <span className="font-semibold">API Key generated successfully!</span>
                      </div>
                      
                      <Snippet 
                        symbol="" 
                        variant="bordered"
                        className="w-full rounded-xl"
                        copyIcon={<Copy className="w-4 h-4" />}
                      >
                        {generatedKey}
                      </Snippet>
                      
                      <p className="text-xs text-[#137333]">
                        Please save this key securely. You won't be able to see it again.
                      </p>
                      
                      <Button
                        color="success"
                        onPress={handleUseGeneratedKey}
                        className="w-full bg-[#e6f4ea] hover:bg-[#ceead6] text-[#137333] font-semibold"
                        radius="full"
                      >
                        Use This Key to Sign In
                      </Button>
                    </CardBody>
                  </Card>
                )}

                {error && (
                  <Chip
                    color="danger"
                    variant="flat"
                    startContent={<AlertCircle className="w-4 h-4" />}
                    className="w-full max-w-full h-auto py-2"
                  >
                    {error}
                  </Chip>
                )}

                <Button
                  variant="light"
                  onPress={() => {
                    setShowGenerate(false)
                    setGeneratedKey('')
                    setError('')
                  }}
                  className="w-full"
                  startContent={<ArrowLeft className="w-4 h-4" />}
                >
                  Back to sign in
                </Button>
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

