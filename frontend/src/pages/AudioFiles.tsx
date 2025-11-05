import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { Upload, Trash2, Download, Music, Loader } from 'lucide-react'
import { format } from 'date-fns'

export default function AudioFiles() {
  const queryClient = useQueryClient()
  const [uploading, setUploading] = useState(false)

  const { data: audioFiles, isLoading } = useQuery({
    queryKey: ['audio', 'list'],
    queryFn: () => apiClient.listAudio(),
  })

  const deleteMutation = useMutation({
    mutationFn: apiClient.deleteAudio,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['audio'] })
    },
  })

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setUploading(true)
    try {
      await apiClient.uploadAudio(file)
      queryClient.invalidateQueries({ queryKey: ['audio'] })
      alert('File uploaded successfully!')
    } catch (error: any) {
      alert(`Upload failed: ${error.response?.data?.detail || error.message}`)
    } finally {
      setUploading(false)
      e.target.value = '' // Reset input
    }
  }

  const handleDownload = async (audioId: string, filename: string) => {
    try {
      const blob = await apiClient.downloadAudio(audioId)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (error: any) {
      alert(`Download failed: ${error.response?.data?.detail || error.message}`)
    }
  }

  const handleDelete = async (audioId: string) => {
    if (confirm('Are you sure you want to delete this audio file?')) {
      try {
        await deleteMutation.mutateAsync(audioId)
      } catch (error) {
        // Error handled by mutation
      }
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Audio Files</h1>
          <p className="mt-2 text-sm text-gray-600">
            Upload and manage your audio files
          </p>
        </div>
        <label className="relative inline-flex items-center px-4 py-2 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 cursor-pointer">
          <Upload className="h-4 w-4 mr-2" />
          {uploading ? 'Uploading...' : 'Upload Audio'}
          <input
            type="file"
            accept="audio/*"
            onChange={handleFileUpload}
            disabled={uploading}
            className="hidden"
          />
        </label>
      </div>

      {isLoading ? (
        <div className="text-center py-12">
          <Loader className="h-8 w-8 animate-spin text-primary-600 mx-auto" />
        </div>
      ) : !audioFiles || audioFiles.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <Music className="h-12 w-12 mx-auto mb-4 text-gray-400" />
          <p className="text-gray-500">No audio files uploaded yet</p>
          <p className="text-sm text-gray-400 mt-2">Upload your first audio file to get started</p>
        </div>
      ) : (
        <div className="bg-white shadow overflow-hidden sm:rounded-md">
          <ul className="divide-y divide-gray-200">
            {audioFiles.map((file) => (
              <li key={file.id}>
                <div className="px-4 py-4 sm:px-6 hover:bg-gray-50 transition-colors">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center">
                      <Music className="h-5 w-5 text-gray-400 mr-3" />
                      <div>
                        <p className="text-sm font-medium text-gray-900">{file.filename}</p>
                        <div className="mt-1 flex items-center text-sm text-gray-500 space-x-4">
                          <span>{format(new Date(file.uploaded_at), 'MMM d, yyyy HH:mm')}</span>
                          <span>•</span>
                          <span>{(file.file_size / 1024 / 1024).toFixed(2)} MB</span>
                          {file.duration && (
                            <>
                              <span>•</span>
                              <span>{Math.round(file.duration)}s</span>
                            </>
                          )}
                          {file.format && (
                            <>
                              <span>•</span>
                              <span className="uppercase">{file.format}</span>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center space-x-2">
                      <button
                        onClick={() => handleDownload(file.id, file.filename)}
                        className="inline-flex items-center px-3 py-1.5 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
                      >
                        <Download className="h-4 w-4 mr-1" />
                        Download
                      </button>
                      <button
                        onClick={() => handleDelete(file.id)}
                        disabled={deleteMutation.isPending}
                        className="inline-flex items-center px-3 py-1.5 border border-transparent text-sm font-medium rounded-md text-red-700 bg-red-100 hover:bg-red-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 disabled:opacity-50"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

