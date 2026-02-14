import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

interface VoiceAIModel {
  id: string
  company: string
  companyLogo: string // SVG or image path
  modelName: string
  features: string[] // 2 lines of features
}

const models: VoiceAIModel[] = [
  {
    id: 'cartesia-1',
    company: 'Cartesia',
    companyLogo: '/cartesia.jpg',
    modelName: 'Sonic-3',
    features: [
      'Ultra-low latency streaming TTS (<100ms) with natural emotions, laughter, and expressive conversations',
      'Context-savvy accuracy handling acronyms, 42 languages, and enterprise-grade security (SOC 2, HIPAA, PCI)'
    ],
  },
  {
    id: 'elevenlabs-1',
    company: 'ElevenLabs',
    companyLogo: '/elevenlabs.jpg',
    modelName: 'ElevenLabs Turbo',
    features: [
      'State-of-the-art voice cloning with minimal audio samples required',
      'Advanced voice conversion and multilingual capabilities with high fidelity'
    ],
  },
  {
    id: 'openai-1',
    company: 'OpenAI',
    companyLogo: '/openai-logo.png',
    modelName: 'OpenAI TTS',
    features: [
      'Neural text-to-speech with natural prosody and expressiveness',
      'Support for multiple voices and languages with studio-quality output'
    ],
  },
  {
    id: 'google-1',
    company: 'Google',
    companyLogo: '🌐',
    modelName: 'Google Cloud TTS',
    features: [
      'WaveNet technology for high-quality, natural-sounding speech',
      'Real-time synthesis with customizable voice parameters and SSML support'
    ],
  },
]

export default function VoiceAIModelsCarousel() {
  const [currentIndex, setCurrentIndex] = useState(0)

  const nextSlide = () => {
    setCurrentIndex((prev) => (prev + 1) % models.length)
  }

  const prevSlide = () => {
    setCurrentIndex((prev) => (prev - 1 + models.length) % models.length)
  }

  const goToSlide = (index: number) => {
    setCurrentIndex(index)
  }

  return (
    <div className="relative w-full">
      <div className="overflow-hidden rounded-lg">
        <div
          className="flex transition-transform duration-500 ease-in-out"
          style={{ transform: `translateX(-${currentIndex * 100}%)` }}
        >
          {models.map((model) => (
            <div
              key={model.id}
              className="min-w-full flex-shrink-0"
            >
              <div className="bg-white border border-gray-200 rounded-lg shadow-sm p-6 mx-2">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-4 flex-1">
                    {/* Company Logo */}
                    <div className="flex-shrink-0">
                      <div className={`w-16 h-16 rounded-lg flex items-center justify-center overflow-hidden ${
                        model.companyLogo.startsWith('/') 
                          ? 'bg-white border border-gray-200' 
                          : 'bg-gradient-to-br from-gray-100 to-gray-200'
                      }`}>
                        {model.companyLogo.startsWith('/') ? (
                          <img 
                            src={model.companyLogo} 
                            alt={model.company}
                            className="w-full h-full object-contain p-2"
                          />
                        ) : (
                          <span className="text-3xl">{model.companyLogo}</span>
                        )}
                      </div>
                    </div>
                    
                    {/* Model Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 mb-2">
                        <h3 className="text-xl font-semibold text-gray-900">
                          {model.modelName}
                        </h3>
                        <span className="px-2.5 py-0.5 bg-gray-100 text-gray-700 rounded-full text-xs font-medium">
                          {model.company}
                        </span>
                      </div>
                      
                      {/* Features */}
                      <div className="space-y-1.5">
                        {model.features.map((feature, idx) => (
                          <p
                            key={idx}
                            className="text-sm text-gray-600 leading-relaxed"
                          >
                            {feature}
                          </p>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Navigation Arrows */}
      <button
        onClick={prevSlide}
        className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-4 bg-white rounded-full p-2 shadow-lg border border-gray-200 hover:bg-gray-50 transition-colors z-10"
        aria-label="Previous model"
      >
        <ChevronLeft className="h-5 w-5 text-gray-600" />
      </button>
      <button
        onClick={nextSlide}
        className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-4 bg-white rounded-full p-2 shadow-lg border border-gray-200 hover:bg-gray-50 transition-colors z-10"
        aria-label="Next model"
      >
        <ChevronRight className="h-5 w-5 text-gray-600" />
      </button>

      {/* Dots Indicator */}
      <div className="flex justify-center gap-2 mt-4">
        {models.map((_, index) => (
          <button
            key={index}
            onClick={() => goToSlide(index)}
            className={`transition-all duration-300 rounded-full ${
              index === currentIndex
                ? 'bg-primary-600 w-8 h-2'
                : 'bg-gray-300 w-2 h-2 hover:bg-gray-400'
            }`}
            aria-label={`Go to slide ${index + 1}`}
          />
        ))}
      </div>
    </div>
  )
}

