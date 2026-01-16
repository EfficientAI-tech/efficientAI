"""
Audio Track for Retell WebRTC Bridge

Custom audio track implementation for sending audio to Retell.
"""

import asyncio
import time
import fractions
from collections import deque
from typing import Optional

try:
    from aiortc.mediastreams import AudioStreamTrack
    from av import AudioFrame
    import numpy as np
except ImportError:
    raise ImportError("aiortc is required for WebRTC bridging. Install with: pip install aiortc")


class RetellAudioTrack(AudioStreamTrack):
    """
    Custom audio track for sending audio to Retell via WebRTC.
    
    Handles PCM audio input and converts it to the format expected by WebRTC.
    """
    
    def __init__(self, sample_rate: int = 24000):
        """
        Initialize the audio track.
        
        Args:
            sample_rate: Audio sample rate in Hz (default 24000 for Retell)
        """
        super().__init__()
        self.sample_rate = sample_rate
        self.samples_per_10ms = sample_rate * 10 // 1000
        self.bytes_per_10ms = self.samples_per_10ms * 2  # 16-bit (2 bytes per sample)
        
        self.timestamp = 0
        self.start_time = time.time()
        self.chunk_queue = deque()  # Queue of (audio_bytes, future)
        
    def add_audio_bytes(self, audio_bytes: bytes) -> asyncio.Future:
        """
        Add audio bytes to the queue for transmission.
        
        Args:
            audio_bytes: Raw PCM audio bytes (16-bit, mono)
            
        Returns:
            Future that completes when the audio is processed
        """
        # Ensure audio is in 10ms chunks
        if len(audio_bytes) % self.bytes_per_10ms != 0:
            # Pad or truncate to nearest 10ms boundary
            chunks = len(audio_bytes) // self.bytes_per_10ms
            audio_bytes = audio_bytes[:chunks * self.bytes_per_10ms]
        
        future = asyncio.get_running_loop().create_future()
        
        # Break into 10ms chunks
        for i in range(0, len(audio_bytes), self.bytes_per_10ms):
            chunk = audio_bytes[i:i + self.bytes_per_10ms]
            # Only the last chunk carries the future
            fut = future if i + self.bytes_per_10ms >= len(audio_bytes) else None
            self.chunk_queue.append((chunk, fut))
        
        return future
    
    async def recv(self) -> AudioFrame:
        """
        Return the next audio frame for WebRTC transmission.
        
        Returns:
            AudioFrame containing the next audio data or silence
        """
        # Synchronize timing
        if self.timestamp > 0:
            wait_time = self.start_time + (self.timestamp / self.sample_rate) - time.time()
            if wait_time > 0:
                await asyncio.sleep(wait_time)
        
        # Get next chunk or use silence
        if self.chunk_queue:
            chunk, future = self.chunk_queue.popleft()
            if future and not future.done():
                future.set_result(True)
        else:
            # Send silence if no audio available
            chunk = bytes(self.bytes_per_10ms)
        
        # Convert bytes to numpy array (int16)
        samples = np.frombuffer(chunk, dtype=np.int16)
        
        # Create AudioFrame
        # Reshape to (1, samples) for mono channel
        frame = AudioFrame.from_ndarray(samples[None, :], layout="mono")
        frame.sample_rate = self.sample_rate
        frame.pts = self.timestamp
        frame.time_base = fractions.Fraction(1, self.sample_rate)
        
        self.timestamp += self.samples_per_10ms
        
        return frame

