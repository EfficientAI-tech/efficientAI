# WebRTC Bridge Implementation

This module implements WebRTC bridging to connect test agents (WebSocket-based) to Retell/Vapi Voice AI agents (WebRTC-based).

## Architecture

```
Test Agent (Voice Bundle)
    ↓ WebSocket
Backend WebSocket Handler
    ↓ Audio Bridge
WebRTC Bridge Service (LiveKit)
    ↓ LiveKit WebRTC
Retell/Vapi Agent
```

## Retell Integration

**IMPORTANT**: Retell uses LiveKit as their WebRTC infrastructure.

The `access_token` returned from Retell's `create_web_call` API is a **LiveKit JWT token** containing:
- `video.room`: The room name (e.g., "web_call_xxx")
- `video.roomJoin`: true
- `iss`: The API key identifier

### Connection Flow

1. Call `create_web_call` on Retell API → Get `access_token` and `call_id`
2. Parse the JWT to extract room name
3. Connect to LiveKit at `wss://retell.livekit.cloud` with the access token
4. Publish audio track
5. Subscribe to remote audio tracks from Retell agent
6. Bridge audio bidirectionally

### LiveKit URL

Retell uses LiveKit Cloud. The URL was found by inspecting `retell-client-js-sdk`:

```
wss://retell-ai-4ihahnq7.livekit.cloud
```

This is hardcoded in the bridge service.

### Token Expiration

**CRITICAL**: Retell access tokens expire after **30 seconds**!

Ensure you:
1. Create the web call
2. **Immediately** initiate the LiveKit connection
3. Don't add delays between web call creation and connection

## Components

### 1. `RetellWebRTCBridge`
- Manages LiveKit room connection to Retell
- Handles audio streaming bidirectionally
- Records conversations
- Extracts room name from JWT token

### 2. `RetellAudioTrack` (legacy, may not be needed with LiveKit)
- Custom audio track for sending audio via aiortc
- Not used with LiveKit SDK

### 3. Integration with Test Agent Bridge
- Connects test agent via WebSocket
- Forwards audio between WebSocket and LiveKit
- Handles recording and result processing

## Dependencies

```bash
pip install livekit
# or
pip install efficientai-ai[livekit]
```

## Testing & Debugging

1. **Enable Debug Logging**:
   - Set log level to DEBUG for `[RetellWebRTC]` messages
   - Check extracted room name from token
   - Monitor connection state changes

2. **Common Issues**:
   - **Token expired**: Connection fails with 401 - call was initiated too late
   - **Wrong URL**: Connection refused - try different LiveKit URL
   - **No audio**: Check if audio tracks are published and subscribed

3. **Verify Token**:
   - The bridge logs the extracted room name
   - If room name extraction fails, check token format

## Example Usage

```python
from app.services.webrtc_bridge.retell_webrtc_bridge import RetellWebRTCBridge

# After creating web call with Retell API
bridge = RetellWebRTCBridge(
    call_id="call_abc123",
    access_token="eyJhbG...",  # LiveKit JWT from create_web_call
    sample_rate=24000
)

# Connect to Retell
connected = await bridge.connect_to_retell()
if connected:
    bridge.is_bridging = True
    
    # Handle incoming audio from Retell
    async def handle_retell_audio(audio_bytes):
        # Forward to test agent
        await send_to_test_agent(audio_bytes)
    
    bridge.on_audio_received = handle_retell_audio
    
    # Send audio from test agent to Retell
    await bridge.receive_audio_from_test_agent(audio_bytes)
    
    # Wait for call to end
    await bridge.wait_for_disconnect(timeout=300)

# Cleanup
await bridge.disconnect()
```
