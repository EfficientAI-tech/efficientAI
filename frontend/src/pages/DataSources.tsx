import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { useState, useRef } from 'react'
import {
  Database,
  Upload,
  Download,
  RefreshCw,
  CheckCircle,
  XCircle,
  AlertCircle,
  FileAudio,
  X,
  Trash2,
  Play,
  Pause,
  Volume2,
} from 'lucide-react'
import { S3FileInfo } from '../types/api'
import Button from '../components/Button'

export default function DataSources() {
  const queryClient = useQueryClient()
  const [showUploadModal, setShowUploadModal] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [customFilename, setCustomFilename] = useState('')
  const [prefix, setPrefix] = useState('')
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [fileToDelete, setFileToDelete] = useState<S3FileInfo | null>(null)
  const [deletingFileKey, setDeletingFileKey] = useState<string | null>(null)
  
  // Audio player state
  const [playingFileKey, setPlayingFileKey] = useState<string | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [loadingAudio, setLoadingAudio] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)

  // Fetch S3 status
  const { data: s3Status, refetch: refetchStatus } = useQuery({
    queryKey: ['s3-status'],
    queryFn: () => apiClient.getS3Status(),
  })

  // Fetch audio files from database (S3 files)
  const { data: s3Files, isLoading: isLoadingFiles, refetch: refetchFiles } = useQuery({
    queryKey: ['s3-files', prefix],
    queryFn: () => apiClient.listS3Files(prefix || undefined),
    enabled: s3Status?.enabled === true,
  })

  // Test connection mutation (uses existing config)
  const testConnectionMutation = useMutation({
    mutationFn: () => apiClient.testS3Connection(),
    onSuccess: () => {
      // Refetch status to update connection state and clear any errors
      refetchStatus()
    },
    onError: () => {
      // Refetch status to update error state
      refetchStatus()
    },
  })

  // Delete file mutation
  const deleteFileMutation = useMutation({
    mutationFn: (fileKey: string) => apiClient.deleteFromS3(fileKey),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['s3-files'] })
      setShowDeleteModal(false)
      setFileToDelete(null)
      setDeletingFileKey(null)
    },
    onError: () => {
      setDeletingFileKey(null)
      // Error will be shown in the modal via deleteFileMutation.error
    },
  })

  const handleDeleteClick = (file: S3FileInfo) => {
    setFileToDelete(file)
    setShowDeleteModal(true)
  }

  const handleDeleteConfirm = () => {
    if (fileToDelete) {
      setDeletingFileKey(fileToDelete.key)
      deleteFileMutation.mutate(fileToDelete.key)
    }
  }

  const handleDeleteCancel = () => {
    setShowDeleteModal(false)
    setFileToDelete(null)
    setDeletingFileKey(null)
  }

  // Audio playback handlers
  const handlePlayAudio = async (file: S3FileInfo) => {
    // If clicking on the same file that's playing, toggle play/pause
    if (playingFileKey === file.key && audioUrl) {
      if (isPlaying) {
        audioRef.current?.pause()
        setIsPlaying(false)
      } else {
        audioRef.current?.play()
        setIsPlaying(true)
      }
      return
    }
    
    // Stop any currently playing audio
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
    }
    
    // Load new audio
    setLoadingAudio(file.key)
    try {
      const { url } = await apiClient.getS3PresignedUrl(file.key)
      setAudioUrl(url)
      setPlayingFileKey(file.key)
      setIsPlaying(true)
      setLoadingAudio(null)
      
      // Play after state update
      setTimeout(() => {
        audioRef.current?.play()
      }, 100)
    } catch (error) {
      console.error('Failed to get audio URL:', error)
      setLoadingAudio(null)
      alert('Failed to load audio file')
    }
  }

  const handleAudioEnded = () => {
    setIsPlaying(false)
  }

  const handleStopAudio = () => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
    }
    setIsPlaying(false)
    setPlayingFileKey(null)
    setAudioUrl(null)
  }

  // Upload file mutation
  const uploadMutation = useMutation({
    mutationFn: ({ file, filename }: { file: File; filename?: string }) => apiClient.uploadToS3(file, filename),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['s3-files'] })
      queryClient.invalidateQueries({ queryKey: ['audio'] })
      setShowUploadModal(false)
      setSelectedFile(null)
      setCustomFilename('')
      alert('✅ File uploaded successfully to S3!')
    },
    onError: (error: any) => {
      alert(`❌ Failed to upload file: ${error.response?.data?.detail || error.message}`)
    },
  })

  const handleTestConnection = () => {
    testConnectionMutation.mutate()
  }

  const handleUpload = (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedFile) return
    uploadMutation.mutate({ 
      file: selectedFile, 
      filename: customFilename.trim() || undefined 
    })
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Data Sources</h1>
          <p className="mt-2 text-sm text-gray-600">
            Connect to S3 buckets to retrieve and store audio files
          </p>
        </div>
        <div className="flex gap-3">
          {s3Status?.enabled && (
            <>
              <Button
                variant="primary"
                onClick={() => setShowUploadModal(true)}
                isLoading={uploadMutation.isPending}
                leftIcon={!uploadMutation.isPending ? <Upload className="h-5 w-5" /> : undefined}
              >
                Upload
              </Button>
              <Button
                variant="secondary"
                onClick={() => refetchFiles()}
                leftIcon={<RefreshCw className="h-5 w-5" />}
              >
                Refresh
              </Button>
            </>
          )}
          <Button
            variant="secondary"
            onClick={handleTestConnection}
            isLoading={testConnectionMutation.isPending}
            leftIcon={!testConnectionMutation.isPending ? <Database className="h-5 w-5" /> : undefined}
          >
            Test Connection
          </Button>
        </div>
      </div>

      {/* S3 Status Card */}
      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Database className="h-6 w-6 text-primary-600" />
            <h2 className="text-xl font-semibold">S3 Connection Status</h2>
          </div>
          {s3Status?.enabled ? (
            <span className="flex items-center gap-2 text-green-600">
              <CheckCircle className="h-5 w-5" />
              Connected
            </span>
          ) : (
            <span className="flex items-center gap-2 text-gray-500">
              <XCircle className="h-5 w-5" />
              Not Connected
            </span>
          )}
        </div>
        {s3Status?.error && (
          <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-4">
            <div className="flex items-start gap-3">
              <AlertCircle className="h-5 w-5 text-red-600 mt-0.5" />
              <div>
                <p className="text-sm text-red-800 font-medium">Connection Error</p>
                <p className="text-sm text-red-700 mt-1">{s3Status.error}</p>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* S3 Files List */}
      {s3Status?.enabled && (
        <div className="bg-white shadow rounded-lg p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold">Audio Files in S3</h2>
            <div className="flex items-center gap-2">
              <input
                type="text"
                placeholder="Filter by prefix..."
                value={prefix}
                onChange={(e) => setPrefix(e.target.value)}
                className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              />
            </div>
          </div>

          {isLoadingFiles ? (
            <div className="text-center py-8 text-gray-500">
              <RefreshCw className="h-8 w-8 mx-auto mb-2 animate-spin" />
              <p>Loading files...</p>
            </div>
          ) : s3Files && s3Files.files.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Filename
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Size
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Last Modified
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {s3Files.files.map((file: S3FileInfo) => (
                    <tr key={file.key} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <FileAudio className="h-5 w-5 text-gray-400" />
                          <span className="text-sm font-medium text-gray-900">{file.filename}</span>
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {formatFileSize(file.size)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {new Date(file.last_modified).toLocaleString()}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm">
                        <div className="flex items-center gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handlePlayAudio(file)}
                            isLoading={loadingAudio === file.key}
                            leftIcon={
                              loadingAudio === file.key ? undefined :
                              playingFileKey === file.key && isPlaying ? 
                                <Pause className="h-4 w-4" /> : 
                                <Play className="h-4 w-4" />
                            }
                            className={`${playingFileKey === file.key && isPlaying ? 'text-green-600 hover:text-green-700 bg-green-50' : 'text-blue-600 hover:text-blue-700'}`}
                            title={playingFileKey === file.key && isPlaying ? 'Pause' : 'Play'}
                          >
                            {playingFileKey === file.key && isPlaying ? 'Pause' : 'Play'}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => apiClient.downloadFromS3(file.key)}
                            leftIcon={<Download className="h-4 w-4" />}
                            className="text-primary-600 hover:text-primary-700"
                          >
                            Download
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDeleteClick(file)}
                            isLoading={deletingFileKey === file.key}
                            disabled={deletingFileKey !== null && deletingFileKey !== file.key}
                            leftIcon={deletingFileKey !== file.key ? <Trash2 className="h-4 w-4" /> : undefined}
                            title="Delete file"
                            className="text-red-600 hover:text-red-700 hover:bg-red-50"
                          >
                            Delete
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="px-6 py-3 bg-gray-50 border-t border-gray-200">
                <p className="text-sm text-gray-600">
                  Showing {s3Files.files.length} of {s3Files.total} files
                </p>
              </div>
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              <Database className="h-12 w-12 mx-auto mb-3 text-gray-300" />
              <p>No audio files found in S3 bucket</p>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowUploadModal(true)}
                className="mt-3"
              >
                Upload your first file
              </Button>
            </div>
          )}
          
          {/* Audio Player Bar */}
          {playingFileKey && audioUrl && (
            <div className="mt-4 bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-lg p-4">
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <Volume2 className="h-5 w-5 text-blue-600" />
                  <span className="text-sm font-medium text-gray-700">Now Playing:</span>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-900 truncate">
                    {s3Files?.files.find((f: S3FileInfo) => f.key === playingFileKey)?.filename || playingFileKey.split('/').pop()}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => {
                      const file = s3Files?.files.find((f: S3FileInfo) => f.key === playingFileKey)
                      if (file) handlePlayAudio(file)
                    }}
                    className="p-2 rounded-full bg-blue-600 text-white hover:bg-blue-700 transition-colors"
                  >
                    {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                  </button>
                  <button
                    onClick={handleStopAudio}
                    className="p-2 rounded-full bg-gray-200 text-gray-600 hover:bg-gray-300 transition-colors"
                    title="Stop"
                  >
                    <XCircle className="h-4 w-4" />
                  </button>
                </div>
                <audio
                  ref={audioRef}
                  src={audioUrl}
                  onEnded={handleAudioEnded}
                  onPause={() => setIsPlaying(false)}
                  onPlay={() => setIsPlaying(true)}
                  controls
                  className="h-8 flex-shrink-0"
                />
              </div>
            </div>
          )}
        </div>
      )}
      
      {/* Hidden audio element */}
      <audio ref={audioRef} className="hidden" />

      {/* Upload Modal */}
      {showUploadModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Upload Audio File</h3>
              <button
                onClick={() => {
                  setShowUploadModal(false)
                  setSelectedFile(null)
                  setCustomFilename('')
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleUpload} className="p-6 space-y-4">
              <div>
                <label htmlFor="file" className="block text-sm font-medium text-gray-700 mb-1">
                  Audio File *
                </label>
                <input
                  id="file"
                  type="file"
                  required
                  accept="audio/*"
                  onChange={(e) => {
                    const file = e.target.files?.[0] || null
                    setSelectedFile(file)
                    // Auto-fill filename with original name (without extension) if custom filename is empty
                    if (file && !customFilename) {
                      const nameWithoutExt = file.name.replace(/\.[^/.]+$/, '')
                      setCustomFilename(nameWithoutExt)
                    }
                  }}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                />
                {selectedFile && (
                  <p className="mt-2 text-sm text-gray-600">
                    Selected: {selectedFile.name} ({(selectedFile.size / 1024 / 1024).toFixed(2)} MB)
                  </p>
                )}
              </div>
              <div>
                <label htmlFor="custom-filename" className="block text-sm font-medium text-gray-700 mb-1">
                  Custom Filename (Optional)
                </label>
                <input
                  id="custom-filename"
                  type="text"
                  value={customFilename}
                  onChange={(e) => setCustomFilename(e.target.value)}
                  placeholder="Enter custom filename (extension will be added automatically)"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                />
                <p className="mt-1 text-xs text-gray-500">
                  If left empty, the original filename will be used. Extension will be added automatically.
                </p>
              </div>
              {uploadMutation.isError && (
                <div className="rounded-md bg-red-50 p-4">
                  <div className="flex">
                    <AlertCircle className="h-5 w-5 text-red-400" />
                    <div className="ml-3">
                      <p className="text-sm text-red-800">
                        {(uploadMutation.error as any)?.response?.data?.detail || 'Upload failed'}
                      </p>
                    </div>
                  </div>
                </div>
              )}
              <div className="flex gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setShowUploadModal(false)
                    setSelectedFile(null)
                    setCustomFilename('')
                  }}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  isLoading={uploadMutation.isPending}
                  disabled={!selectedFile}
                  className="flex-1"
                >
                  Upload
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && fileToDelete && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-red-600">Confirm Deletion</h3>
              <button
                onClick={handleDeleteCancel}
                disabled={deletingFileKey !== null}
                className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6">
              <div className="flex items-start gap-3 mb-4">
                <AlertCircle className="h-5 w-5 text-red-600 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-sm text-gray-800 font-medium mb-1">
                    Are you sure you want to delete this file?
                  </p>
                  <p className="text-sm text-gray-600">
                    <span className="font-medium">{fileToDelete.filename}</span>
                    <span className="text-gray-500 ml-2">({formatFileSize(fileToDelete.size)})</span>
                  </p>
                  <p className="text-xs text-red-600 mt-2">
                    This action cannot be undone.
                  </p>
                </div>
              </div>
              {deleteFileMutation.isError && (
                <div className="mb-4 rounded-md bg-red-50 p-3">
                  <p className="text-sm text-red-800">
                    {(deleteFileMutation.error as any)?.response?.data?.detail || 'Failed to delete file'}
                  </p>
                </div>
              )}
              <div className="flex gap-3 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleDeleteCancel}
                  disabled={deletingFileKey !== null}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  variant="primary"
                  onClick={handleDeleteConfirm}
                  isLoading={deletingFileKey !== null}
                  disabled={deletingFileKey !== null}
                  className="flex-1 bg-red-600 hover:bg-red-700 text-white"
                >
                  {deletingFileKey !== null ? 'Deleting...' : 'Delete'}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

