const PEAK_WIDTH = 512

function readFourCC(view: DataView, offset: number): string {
  return String.fromCharCode(
    view.getUint8(offset),
    view.getUint8(offset + 1),
    view.getUint8(offset + 2),
    view.getUint8(offset + 3),
  )
}

export function extractWavPeaks(
  arrayBuffer: ArrayBuffer,
  stereo: boolean,
  width = PEAK_WIDTH,
): { duration: number; peaks: ArrayBuffer[]; stereo: boolean } | null {
  try {
    if (arrayBuffer.byteLength < 44) return null
    const view = new DataView(arrayBuffer)
    if (readFourCC(view, 0) !== 'RIFF' || readFourCC(view, 8) !== 'WAVE') return null

    let offset = 12
    let numChannels = 0
    let sampleRate = 0
    let bitsPerSample = 16
    let dataOffset = 0
    let dataSize = 0

    while (offset + 8 <= arrayBuffer.byteLength) {
      const chunkId = readFourCC(view, offset)
      const chunkSize = view.getUint32(offset + 4, true)
      const chunkDataOffset = offset + 8
      if (chunkId === 'fmt ') {
        numChannels = view.getUint16(chunkDataOffset + 2, true)
        sampleRate = view.getUint32(chunkDataOffset + 4, true)
        bitsPerSample = view.getUint16(chunkDataOffset + 14, true)
      } else if (chunkId === 'data') {
        dataOffset = chunkDataOffset
        dataSize = chunkSize
      }
      offset = chunkDataOffset + chunkSize + (chunkSize % 2)
    }

    if (!dataOffset || !sampleRate || bitsPerSample !== 16 || numChannels < 1) return null
    if (dataOffset % 2 !== 0) return null
    if (dataOffset + dataSize > arrayBuffer.byteLength) return null

    const frameCount = Math.floor(dataSize / (bitsPerSample / 8) / numChannels)
    if (frameCount <= 0) return null

    const samples = new Int16Array(arrayBuffer, dataOffset, frameCount * numChannels)
    const useStereo = stereo && numChannels >= 2
    const duration = frameCount / sampleRate

    const downsampleChannel = (channelIndex: number): ArrayBuffer => {
      const peaks = new Float32Array(width * 2)
      const block = Math.max(1, Math.floor(frameCount / width))
      for (let i = 0; i < width; i++) {
        const start = i * block
        const end = Math.min(frameCount, start + block)
        let min = 0
        let max = 0
        for (let j = start; j < end; j++) {
          const v = samples[j * numChannels + channelIndex] / 32768
          if (v < min) min = v
          if (v > max) max = v
        }
        peaks[i * 2] = min
        peaks[i * 2 + 1] = max
      }
      return peaks.buffer
    }

    const peaks: ArrayBuffer[] = useStereo
      ? [downsampleChannel(0), downsampleChannel(1)]
      : [downsampleChannel(0)]

    return { duration, peaks, stereo: useStereo }
  } catch {
    return null
  }
}

export function isWavBuffer(arrayBuffer: ArrayBuffer): boolean {
  if (arrayBuffer.byteLength < 12) return false
  const view = new DataView(arrayBuffer)
  return readFourCC(view, 0) === 'RIFF' && readFourCC(view, 8) === 'WAVE'
}
