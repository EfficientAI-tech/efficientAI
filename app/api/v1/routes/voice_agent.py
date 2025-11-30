"""
Voice Agent API Routes
API endpoints for managing voice agent WebSocket connections.
"""

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request, status
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Dict, Any, Optional, List
from loguru import logger

from app.database import get_db
from app.dependencies import get_organization_id, get_api_key
from app.models.database import AIProvider, ModelProvider
from app.core.encryption import decrypt_api_key
from app.services.voice_agent.bot_fast_api import run_bot
from app.services.s3_service import s3_service

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
        
        # Get agent_id, persona_id and scenario_id from query params
        agent_id = websocket.query_params.get("agent_id")
        persona_id = websocket.query_params.get("persona_id")
        scenario_id = websocket.query_params.get("scenario_id")
        
        # Determine which AI Provider to use
        # Priority: 1) Agent's ai_provider_id, 2) Agent's voice_bundle's providers, 3) Default Google
        ai_provider = None
        agent = None
        
        if agent_id:
            try:
                from app.models.database import Agent, VoiceBundle
                agent_uuid = UUID(agent_id)
                agent = db.query(Agent).filter(
                    Agent.id == agent_uuid,
                    Agent.organization_id == organization_id
                ).first()
                
                if agent:
                    # If agent has ai_provider_id, use that
                    if agent.ai_provider_id:
                        ai_provider = db.query(AIProvider).filter(
                            AIProvider.id == agent.ai_provider_id,
                            AIProvider.organization_id == organization_id,
                            AIProvider.is_active == True
                        ).first()
                    # If agent has voice_bundle_id, we could use it in the future
                    # For now, fall back to Google
                    elif agent.voice_bundle_id:
                        # Voice Bundle support can be added here in the future
                        # For now, use default Google provider
                        pass
            except ValueError:
                pass
        
        # Fall back to Google AI Provider if no agent-specific provider found
        if not ai_provider:
            ai_provider = db.query(AIProvider).filter(
                AIProvider.organization_id == organization_id,
                AIProvider.provider == ModelProvider.GOOGLE,
                AIProvider.is_active == True
            ).first()
        
        if not ai_provider:
            await websocket.close(
                code=1008, 
                reason="AI Provider not configured. Please configure an AI Provider in AI Providers settings or select one when creating the agent."
            )
            return
        
        # Decrypt API key
        try:
            google_api_key = decrypt_api_key(ai_provider.api_key)
            # Validate the decrypted key
            if not google_api_key or not google_api_key.strip():
                logger.error("Decrypted API key is empty")
                await websocket.close(
                    code=1008,
                    reason="API key is empty. Please configure a valid API key in AI Providers settings."
                )
                return
        except Exception as e:
            logger.error(f"Failed to decrypt API key: {e}", exc_info=True)
            await websocket.close(
                code=1008,
                reason=f"Failed to decrypt API key: {str(e)}"
            )
            return
        
        system_instruction = None
        instruction_parts = []
        
        # Build system instruction as a bundle: Agent + Persona + Scenario
        from app.models.database import Agent, Persona, Scenario
        
        # 1. Add Agent description (base instruction)
        if agent_id:
            try:
                agent_uuid = UUID(agent_id)
                agent = db.query(Agent).filter(
                    Agent.id == agent_uuid,
                    Agent.organization_id == organization_id
                ).first()
                if agent and agent.description:
                    instruction_parts.append(agent.description)
            except ValueError:
                pass
        
        # 2. Add Persona information (characteristics)
        if persona_id:
            try:
                persona_uuid = UUID(persona_id)
                persona = db.query(Persona).filter(
                    Persona.id == persona_uuid,
                    Persona.organization_id == organization_id
                ).first()
                if persona:
                    persona_parts = []
                    persona_parts.append(f"\n\nPersona: {persona.name}")
                    if persona.language:
                        persona_parts.append(f"Language: {persona.language.value}")
                    if persona.accent:
                        persona_parts.append(f"Accent: {persona.accent.value}")
                    if persona.gender:
                        persona_parts.append(f"Gender: {persona.gender.value}")
                    if persona.background_noise and persona.background_noise.value != "none":
                        persona_parts.append(f"Background noise: {persona.background_noise.value}")
                    
                    if persona_parts:
                        instruction_parts.append("\n".join(persona_parts))
            except ValueError:
                pass
        
        # 3. Add Scenario information (context and goals)
        if scenario_id:
            try:
                scenario_uuid = UUID(scenario_id)
                scenario = db.query(Scenario).filter(
                    Scenario.id == scenario_uuid,
                    Scenario.organization_id == organization_id
                ).first()
                if scenario:
                    scenario_parts = []
                    scenario_parts.append(f"\n\nScenario: {scenario.name}")
                    if scenario.description:
                        scenario_parts.append(f"Description: {scenario.description}")
                    if scenario.required_info:
                        required_info_str = ", ".join([f"{k}: {v}" for k, v in scenario.required_info.items()]) if isinstance(scenario.required_info, dict) else str(scenario.required_info)
                        if required_info_str:
                            scenario_parts.append(f"Required information to collect: {required_info_str}")
                    
                    if scenario_parts:
                        instruction_parts.append("\n".join(scenario_parts))
            except ValueError:
                pass
        
        # Combine all parts into final system instruction
        if instruction_parts:
            system_instruction = "\n".join(instruction_parts)
        
        # Run the bot with the decrypted API key
        call_metadata = None
        try:
            call_metadata = await run_bot(
                websocket, 
                google_api_key, 
                system_instruction, 
                str(organization_id),
                agent_id,
                persona_id,
                scenario_id
            )
        except Exception as bot_error:
            logger.error(f"Error in run_bot: {bot_error}", exc_info=True)
            # Continue to try creating evaluator result if we have metadata
        
        # Create evaluator result if we have the required data (only if no error)
        if call_metadata and call_metadata.get("s3_key") and not call_metadata.get("error") and agent_id and persona_id and scenario_id:
            try:
                from app.models.database import Evaluator, EvaluatorResult, EvaluatorResultStatus, Scenario
                from app.workers.celery_app import process_evaluator_result_task
                import random
                
                # Find evaluator by agent, persona, scenario
                evaluator = db.query(Evaluator).filter(
                    Evaluator.agent_id == UUID(agent_id),
                    Evaluator.persona_id == UUID(persona_id),
                    Evaluator.scenario_id == UUID(scenario_id),
                    Evaluator.organization_id == organization_id
                ).first()
                
                if evaluator:
                    # Get scenario name
                    scenario = db.query(Scenario).filter(Scenario.id == UUID(scenario_id)).first()
                    scenario_name = scenario.name if scenario else "Unknown Scenario"
                    
                    # Generate unique 6-digit result ID
                    max_attempts = 100
                    result_id = None
                    for _ in range(max_attempts):
                        candidate_id = f"{random.randint(100000, 999999)}"
                        existing = db.query(EvaluatorResult).filter(EvaluatorResult.result_id == candidate_id).first()
                        if not existing:
                            result_id = candidate_id
                            break
                    
                    if not result_id:
                        logger.error("Failed to generate unique result ID")
                    else:
                        # Create evaluator result
                        evaluator_result = EvaluatorResult(
                            result_id=result_id,
                            organization_id=organization_id,
                            evaluator_id=evaluator.id,
                            agent_id=UUID(agent_id),
                            persona_id=UUID(persona_id),
                            scenario_id=UUID(scenario_id),
                            name=scenario_name,
                            duration_seconds=call_metadata.get("duration"),
                            status=EvaluatorResultStatus.IN_PROGRESS,
                            audio_s3_key=call_metadata.get("s3_key")
                        )
                        db.add(evaluator_result)
                        db.commit()
                        db.refresh(evaluator_result)
                        
                        # Trigger Celery task
                        task = process_evaluator_result_task.delay(str(evaluator_result.id))
                        evaluator_result.celery_task_id = task.id
                        db.commit()
                        
                        logger.info(f"✅ Created evaluator result {result_id} and triggered processing task")
                else:
                    pass
            except Exception as e:
                logger.error(f"Error creating evaluator result: {e}", exc_info=True)
        
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
    
    # Get agent_id, persona_id and scenario_id from query params first
    agent_id = request.query_params.get("agent_id")
    persona_id = request.query_params.get("persona_id")
    scenario_id = request.query_params.get("scenario_id")
    
    # Determine which AI Provider to use based on agent configuration
    ai_provider = None
    agent = None
    
    if agent_id:
        try:
            from app.models.database import Agent
            agent_uuid = UUID(agent_id)
            agent = db.query(Agent).filter(
                Agent.id == agent_uuid,
                Agent.organization_id == organization_id
            ).first()
            
            if agent and agent.ai_provider_id:
                ai_provider = db.query(AIProvider).filter(
                    AIProvider.id == agent.ai_provider_id,
                    AIProvider.organization_id == organization_id,
                    AIProvider.is_active == True
                ).first()
        except ValueError:
            pass
    
    # Fall back to Google AI Provider if no agent-specific provider found
    if not ai_provider:
        ai_provider = db.query(AIProvider).filter(
            AIProvider.organization_id == organization_id,
            AIProvider.provider == ModelProvider.GOOGLE,
            AIProvider.is_active == True
        ).first()
    
    if not ai_provider:
        print("[BACKEND] ❌ AI Provider not configured")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AI Provider not configured. Please configure an AI Provider in AI Providers settings or select one when creating the agent."
        )
    
    print(f"[BACKEND] ✅ AI Provider found: {ai_provider.provider.value}")
    
    # Determine WebSocket protocol based on request
    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host", f"localhost:{settings.PORT}")
    base_url = f"{scheme}://{host}"
    
    # The WebSocket endpoint path with API key as query parameter
    ws_url = f"{base_url}{settings.API_V1_PREFIX}/voice-agent/ws?X-API-Key={api_key}"
    
    # Append agent_id, persona_id and scenario_id if present
    if agent_id:
        ws_url += f"&agent_id={agent_id}"
    if persona_id:
        ws_url += f"&persona_id={persona_id}"
    if scenario_id:
        ws_url += f"&scenario_id={scenario_id}"
    
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


@router.get("/audio", response_model=List[Dict[str, Any]])
async def list_voice_agent_audio_files(
    organization_id: UUID = Depends(get_organization_id),
    max_keys: int = 1000,
):
    """
    List audio files for voice agent conversations for the current organization.
    
    Args:
        organization_id: Organization ID from API key
        max_keys: Maximum number of files to return
        
    Returns:
        List of audio file metadata with keys: key, size, last_modified, filename
    """
    try:
        files = s3_service.list_audio_files(
            organization_id=str(organization_id),
            max_keys=max_keys
        )
        return files
    except Exception as e:
        logger.error(f"Error listing voice agent audio files: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list audio files: {str(e)}"
        )

