"""
Voice Agent API Routes
API endpoints for managing voice agent WebSocket connections.
"""

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request, status
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Dict, Any, Optional

from app.database import get_db
from app.dependencies import get_organization_id, get_api_key
from app.models.database import AIProvider, ModelProvider
from app.core.encryption import decrypt_api_key
from app.services.voice_agent.bot_fast_api import run_bot

router = APIRouter(prefix="/voice-agent", tags=["voice-agent"])


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
):
    """
    WebSocket endpoint for voice agent connection.
    Requires API key authentication via query parameter.
    """
    # Get API key from query parameters
    api_key = websocket.query_params.get("X-API-Key") or websocket.query_params.get("api_key")
    
    if not api_key:
        print("WebSocket connection rejected: No API key provided")
        await websocket.close(code=1008, reason="API key required")
        return
    
    print(f"WebSocket connection attempt with API key: {api_key[:10]}...")
    await websocket.accept()
    print("WebSocket connection accepted")
    
    try:
        # Get database session
        db = next(get_db())
        
        # Get organization ID from API key
        from app.core.security import get_api_key_organization_id, verify_api_key
        
        # Verify API key
        if not verify_api_key(api_key, db):
            print("WebSocket connection rejected: Invalid API key")
            await websocket.close(code=1008, reason="Invalid API key")
            db.close()
            return
        
        organization_id = get_api_key_organization_id(api_key, db)
        
        if not organization_id:
            print("WebSocket connection rejected: Could not get organization ID")
            await websocket.close(code=1008, reason="Invalid API key")
            db.close()
            return
        
        # Get Google AI Provider for this organization
        ai_provider = db.query(AIProvider).filter(
            AIProvider.organization_id == organization_id,
            AIProvider.provider == ModelProvider.GOOGLE,
            AIProvider.is_active == True
        ).first()
        
        if not ai_provider:
            await websocket.close(
                code=1008, 
                reason="Google AI Provider not configured. Please configure a Google API key in AI Providers settings."
            )
            return
        
        # Decrypt API key
        try:
            google_api_key = decrypt_api_key(ai_provider.api_key)
        except Exception as e:
            await websocket.close(
                code=1008,
                reason=f"Failed to decrypt API key: {str(e)}"
            )
            return
        
        # Run the bot with the decrypted API key
        print("Starting voice agent bot...")
        print(f"WebSocket client state: {websocket.client_state}")
        print(f"WebSocket application state: {websocket.application_state}")
        try:
            await run_bot(websocket, google_api_key)
            print("Voice agent bot finished")
        except Exception as bot_error:
            print(f"Error in run_bot: {bot_error}")
            import traceback
            traceback.print_exc()
            raise
        
    except WebSocketDisconnect:
        print("WebSocket disconnected by client")
    except Exception as e:
        print(f"Exception in voice agent WebSocket: {e}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.close(code=1011, reason=f"Server error: {str(e)}")
        except:
            pass
    finally:
        try:
            if 'db' in locals():
                db.close()
        except:
            pass


@router.options("/connect")
async def bot_connect_options():
    """Handle CORS preflight requests."""
    from fastapi.responses import Response
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Credentials": "true",
        }
    )

@router.post("/connect", response_model=Dict[str, Any])
@router.get("/connect", response_model=Dict[str, Any])
async def bot_connect(
    request: Request,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get WebSocket connection URL for voice agent.
    Returns the WebSocket URL that the client should connect to.
    Accepts API key from header, query parameter, cookies, or request body.
    
    Supports both GET and POST requests for compatibility with different client implementations.
    
    Note: This endpoint is called by Pipecat's startBotAndConnect which may not
    send authentication headers. We try multiple methods to get the API key.
    """
    print("=" * 80)
    print(f"[BACKEND] /connect endpoint called at {__import__('datetime').datetime.now()}")
    print(f"[BACKEND] Request method: {request.method}")
    print(f"[BACKEND] Request URL: {request.url}")
    print(f"[BACKEND] Request headers: {dict(request.headers)}")
    print(f"[BACKEND] Request cookies: {dict(request.cookies)}")
    print(f"[BACKEND] Query params: {dict(request.query_params)}")
    
    # Get API key - prioritize cookies since Pipecat can send them automatically
    # Then try headers, then query params
    api_key = request.cookies.get("api_key")
    print(f"[BACKEND] API key from cookies: {'found' if api_key else 'not found'}")
    
    if not api_key:
        api_key = request.headers.get("X-API-Key")
        print(f"[BACKEND] API key from headers: {'found' if api_key else 'not found'}")
    
    if not api_key:
        api_key = request.query_params.get("X-API-Key") or request.query_params.get("api_key")
        print(f"[BACKEND] API key from query params: {'found' if api_key else 'not found'}")
    
    # Also try to extract from the full URL (in case query params aren't parsed)
    if not api_key:
        url_str = str(request.url)
        if "X-API-Key=" in url_str:
            try:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(url_str)
                params = parse_qs(parsed.query)
                api_key = params.get("X-API-Key", [None])[0] or params.get("api_key", [None])[0]
                print(f"[BACKEND] API key from URL parsing: {'found' if api_key else 'not found'}")
            except Exception as e:
                print(f"[BACKEND] Error parsing URL: {e}")
    
    # Don't read request body - it can only be read once and might cause issues
    # If we need to read body, we'd need to cache it, but cookies should work
    
    from app.config import settings
    
    # If no API key is provided, we can't return a valid WebSocket URL
    # because the WebSocket endpoint requires authentication.
    # However, to allow Pipecat's startBotAndConnect to work, we'll return
    # a WebSocket URL that the client can modify, or we'll use a session-based approach.
    # For now, let's require the API key but make it easier to provide.
    if not api_key:
        print("[BACKEND] ❌ No API key found, returning 401")
        raise HTTPException(
            status_code=401, 
            detail="API key is required. Please ensure you are logged in and the API key is set."
        )
    
    print(f"[BACKEND] API key found: {api_key[:10]}... (truncated)")
    
    # Verify API key if provided
    from app.core.security import verify_api_key, get_api_key_organization_id
    if not verify_api_key(api_key, db):
        print("[BACKEND] ❌ API key verification failed")
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    print("[BACKEND] ✅ API key verified")
    
    organization_id = get_api_key_organization_id(api_key, db)
    if not organization_id:
        print("[BACKEND] ❌ Could not get organization ID")
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    print(f"[BACKEND] Organization ID: {organization_id}")
    
    # Verify Google AI Provider is configured
    ai_provider = db.query(AIProvider).filter(
        AIProvider.organization_id == organization_id,
        AIProvider.provider == ModelProvider.GOOGLE,
        AIProvider.is_active == True
    ).first()
    
    if not ai_provider:
        print("[BACKEND] ❌ Google AI Provider not configured")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google AI Provider not configured. Please configure a Google API key in AI Providers settings."
        )
    
    print("[BACKEND] ✅ Google AI Provider found")
    
    # Determine WebSocket protocol based on request
    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host", f"localhost:{settings.PORT}")
    base_url = f"{scheme}://{host}"
    
    # The WebSocket endpoint path with API key as query parameter
    ws_url = f"{base_url}{settings.API_V1_PREFIX}/voice-agent/ws?X-API-Key={api_key}"
    
    # Return the response in the format Pipecat expects
    # Pipecat expects a JSON response with ws_url field
    # The response should be simple and match exactly what Pipecat expects
    from fastapi.responses import JSONResponse
    response_data = {
        "ws_url": ws_url
    }
    print(f"[BACKEND] ✅ Returning WebSocket URL: {ws_url}")
    print(f"[BACKEND] Response data: {response_data}")
    print("=" * 80)
    
    # Return JSON response - CORS is handled by middleware
    return JSONResponse(
        content=response_data,
        status_code=200,
        headers={
            "Content-Type": "application/json",
        }
    )

