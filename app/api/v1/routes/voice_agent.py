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
from app.models.database import AIProvider, ModelProvider, Integration, IntegrationPlatform
from app.core.encryption import decrypt_api_key
from app.services.voice_agent.bot_fast_api import run_bot
from app.services.voice_agent.voice_bundle import run_voice_bundle_fastapi
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
        
        # Fetch agent and voice bundle once for routing and instructions
        agent = None
        voice_bundle = None
        try:
            if agent_id:
                from app.models.database import Agent, VoiceBundle
                agent_uuid = UUID(agent_id)
                agent = db.query(Agent).filter(
                    Agent.id == agent_uuid,
                    Agent.organization_id == organization_id
                ).first()
                if agent and agent.voice_bundle_id:
                    voice_bundle = db.query(VoiceBundle).filter(
                        VoiceBundle.id == agent.voice_bundle_id,
                        VoiceBundle.organization_id == organization_id
                    ).first()
        except ValueError:
            pass

        use_voice_bundle_pipeline = bool(voice_bundle and voice_bundle.bundle_type == "stt_llm_tts")

        def resolve_api_key_for_provider(provider: ModelProvider) -> str | None:
            """Resolve API key from AIProvider (preferred) or Integration for given provider."""
            from sqlalchemy import func
            # 1) AIProvider (handle both string and enum comparisons)
            provider_value = provider.value if hasattr(provider, 'value') else provider
            
            ai_provider_rec = db.query(AIProvider).filter(
                AIProvider.organization_id == organization_id,
                AIProvider.provider == provider_value,
                AIProvider.is_active == True,
            ).first()
            
            # If not found, try case-insensitive match
            if not ai_provider_rec:
                ai_provider_rec = db.query(AIProvider).filter(
                    AIProvider.organization_id == organization_id,
                    func.lower(AIProvider.provider) == provider_value.lower(),
                    AIProvider.is_active == True,
                ).first()
            if ai_provider_rec:
                try:
                    return decrypt_api_key(ai_provider_rec.api_key)
                except Exception as e:
                    logger.error(f"Failed to decrypt AIProvider key for {provider}: {e}", exc_info=True)
            # 2) Integration mapping (only for platforms that exist in IntegrationPlatform)
            platform_map = {
                ModelProvider.DEEPGRAM: IntegrationPlatform.DEEPGRAM,
                ModelProvider.CARTESIA: IntegrationPlatform.CARTESIA,
            }
            plat = platform_map.get(provider)
            if plat:
                # Handle both string and enum comparisons for platform
                plat_value = plat.value if hasattr(plat, 'value') else plat
                integ = db.query(Integration).filter(
                    Integration.organization_id == organization_id,
                    Integration.platform == plat_value,
                    Integration.is_active == True,
                ).first()
                
                # If not found, try case-insensitive match
                if not integ:
                    integ = db.query(Integration).filter(
                        Integration.organization_id == organization_id,
                        func.lower(Integration.platform) == plat_value.lower(),
                        Integration.is_active == True,
                    ).first()
                
                if integ:
                    try:
                        return decrypt_api_key(integ.api_key)
                    except Exception as e:
                        logger.error(f"Failed to decrypt Integration key for {provider}: {e}", exc_info=True)
            return None

        # Determine which AI Provider to use (only needed for S2S/Gemini path)
        # Priority: 1) Agent's ai_provider_id, 2) Default Google
        ai_provider = None
        google_api_key = None
        if not use_voice_bundle_pipeline:
            if agent and agent.ai_provider_id:
                ai_provider = db.query(AIProvider).filter(
                    AIProvider.id == agent.ai_provider_id,
                    AIProvider.organization_id == organization_id,
                    AIProvider.is_active == True
                ).first()

            # Fall back to Google AI Provider if no agent-specific provider found
            if not ai_provider:
                from sqlalchemy import func
                google_value = ModelProvider.GOOGLE.value
                ai_provider = db.query(AIProvider).filter(
                    AIProvider.organization_id == organization_id,
                    AIProvider.provider == google_value,
                    AIProvider.is_active == True
                ).first()
                # If not found, try case-insensitive match
                if not ai_provider:
                    ai_provider = db.query(AIProvider).filter(
                        AIProvider.organization_id == organization_id,
                        func.lower(AIProvider.provider) == google_value.lower(),
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
        
        # 1. Add Agent description (base instruction) and get voice bundle for model
        model_name = None
        if agent:
            if agent.description:
                instruction_parts.append(agent.description)
            if voice_bundle and voice_bundle.bundle_type == "s2s" and voice_bundle.s2s_model:
                model_name = voice_bundle.s2s_model
        
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
        
        # Generate result_id BEFORE running bot (for meaningful S3 path)
        # Evaluator is only created if persona_id and scenario_id are provided
        # But evaluator results can be created even without persona/scenario
        evaluator = None
        result_id = None
        scenario_name = "Test Call"  # Default name for calls without scenario
        
        # Generate result_id for all test calls (with or without persona/scenario)
        if agent_id:
            try:
                from app.models.database import EvaluatorResult
                import random
                
                # Generate unique 6-digit result ID
                max_attempts = 100
                for _ in range(max_attempts):
                    candidate_id = f"{random.randint(100000, 999999)}"
                    existing = db.query(EvaluatorResult).filter(EvaluatorResult.result_id == candidate_id).first()
                    if not existing:
                        result_id = candidate_id
                        break
                
                if not result_id:
                    logger.warning("Failed to generate unique result ID, will use UUID in S3 path")
            except Exception as e:
                logger.warning(f"Error generating result_id: {e}")
        
        # Find or create evaluator only if persona_id and scenario_id are provided
        if agent_id and persona_id and scenario_id:
            try:
                from app.models.database import Evaluator, EvaluatorResult, EvaluatorResultStatus, Scenario
                from app.api.v1.routes.evaluators import generate_unique_evaluator_id
                import random
                
                # Find evaluator by agent, persona, scenario
                evaluator = db.query(Evaluator).filter(
                    Evaluator.agent_id == UUID(agent_id),
                    Evaluator.persona_id == UUID(persona_id),
                    Evaluator.scenario_id == UUID(scenario_id),
                    Evaluator.organization_id == organization_id
                ).first()
                
                # If no evaluator exists, create one automatically for test voice agent calls
                if not evaluator:
                    logger.info(f"Creating evaluator automatically for test voice agent: agent={agent_id}, persona={persona_id}, scenario={scenario_id}")
                    evaluator_id = generate_unique_evaluator_id(db)
                    evaluator = Evaluator(
                        evaluator_id=evaluator_id,
                        organization_id=organization_id,
                        agent_id=UUID(agent_id),
                        persona_id=UUID(persona_id),
                        scenario_id=UUID(scenario_id),
                        tags=["auto-created", "test-voice-agent"]
                    )
                    db.add(evaluator)
                    db.commit()
                    db.refresh(evaluator)
                    logger.info(f"✅ Created evaluator {evaluator_id} for test voice agent")
                
                if evaluator:
                    # Get scenario name
                    scenario = db.query(Scenario).filter(Scenario.id == UUID(scenario_id)).first()
                    scenario_name = scenario.name if scenario else "Unknown Scenario"
            except Exception as e:
                logger.warning(f"Error finding/creating evaluator or generating result_id: {e}")
        
        # Check if this is a test agent that should bridge to Voice AI agent
        # This happens when evaluator is run via the run_evaluator_task
        test_agent_bridge_mode = False
        retell_call_id = None
        retell_access_token = None
        retell_sample_rate = None
        
        if evaluator and agent and agent.voice_bundle_id and agent.voice_ai_integration_id:
            # Check if there's an active call for this evaluator
            # The call info is stored in the EvaluatorResult's error_message field temporarily
            try:
                from app.models.database import EvaluatorResult
                # Find the most recent result for this evaluator that has call info
                active_result = db.query(EvaluatorResult).filter(
                    EvaluatorResult.evaluator_id == evaluator.id,
                    EvaluatorResult.status == EvaluatorResultStatus.QUEUED.value,
                    EvaluatorResult.error_message.isnot(None),
                    EvaluatorResult.error_message.like("call_id:%")
                ).order_by(EvaluatorResult.timestamp.desc()).first()
                
                if active_result and active_result.error_message:
                    # Parse call info from error_message: "call_id:xxx|access_token:yyy|sample_rate:zzz"
                    call_info_parts = active_result.error_message.split("|")
                    for part in call_info_parts:
                        if part.startswith("call_id:"):
                            retell_call_id = part.split(":", 1)[1]
                        elif part.startswith("access_token:"):
                            retell_access_token = part.split(":", 1)[1]
                        elif part.startswith("sample_rate:"):
                            retell_sample_rate = int(part.split(":", 1)[1])
                    
                    if retell_call_id and retell_access_token:
                        test_agent_bridge_mode = True
                        logger.info(
                            f"[VoiceAgent] Test agent bridge mode detected: "
                            f"evaluator={evaluator.evaluator_id}, call_id={retell_call_id}"
                        )
            except Exception as e:
                logger.warning(f"[VoiceAgent] Error checking for bridge mode: {e}", exc_info=True)
        
        # Run the bot with the appropriate pipeline
        call_metadata = None
        try:
            if use_voice_bundle_pipeline:
                # Resolve per-provider keys for voice bundle
                stt_provider = voice_bundle.stt_provider if voice_bundle else None
                tts_provider = voice_bundle.tts_provider if voice_bundle else None
                llm_provider = voice_bundle.llm_provider if voice_bundle else None

                stt_api_key = resolve_api_key_for_provider(stt_provider) if stt_provider else None
                tts_api_key = resolve_api_key_for_provider(tts_provider) if tts_provider else None
                llm_api_key = resolve_api_key_for_provider(llm_provider) if llm_provider else None

                # If in bridge mode, we need to bridge test agent to Retell call
                # For now, we'll run the voice bundle normally and note that bridging
                # requires WebRTC implementation on the backend
                if test_agent_bridge_mode:
                    logger.info(
                        f"[VoiceAgent] Bridge mode: Test agent should connect to Retell call {retell_call_id}. "
                        f"Full WebRTC bridging requires additional implementation."
                    )
                    # TODO: Implement WebRTC bridging between test agent WebSocket and Retell call
                    # This would require:
                    # 1. Joining Retell call using WebRTC (aiortc or similar)
                    # 2. Bridging audio streams bidirectionally
                    # 3. Recording the bridged conversation

                call_metadata = await run_voice_bundle_fastapi(
                    websocket,
                    system_instruction,
                    str(organization_id),
                    agent_id,
                    persona_id,
                    scenario_id,
                    evaluator_id=str(evaluator.id) if evaluator else None,
                    result_id=result_id,
                    voice_bundle=voice_bundle,
                    stt_api_key=stt_api_key,
                    tts_api_key=tts_api_key,
                    llm_api_key=llm_api_key,
                )
            else:
                call_metadata = await run_bot(
                    websocket,
                    google_api_key,
                    system_instruction,
                    str(organization_id),
                    agent_id,
                    persona_id,
                    scenario_id,
                    evaluator_id=str(evaluator.id) if evaluator else None,
                    result_id=result_id,
                    model_name=model_name,  # Pass model name from voice bundle
                )
        except Exception as bot_error:
            logger.error(f"Error in run_bot: {bot_error}", exc_info=True)
            # Continue to try creating evaluator result if we have metadata
        
        # Create evaluator result if we have the required data (only if no error)
        # Create evaluator result for all test calls (with or without persona/scenario)
        if call_metadata and call_metadata.get("s3_key") and not call_metadata.get("error") and agent_id and result_id:
            # If we don't have evaluator but have persona/scenario, try to create one
            if not evaluator and agent_id and persona_id and scenario_id:
                try:
                    from app.models.database import Evaluator, Scenario
                    from app.api.v1.routes.evaluators import generate_unique_evaluator_id
                    import random
                    
                    evaluator = db.query(Evaluator).filter(
                        Evaluator.agent_id == UUID(agent_id),
                        Evaluator.persona_id == UUID(persona_id),
                        Evaluator.scenario_id == UUID(scenario_id),
                        Evaluator.organization_id == organization_id
                    ).first()
                    
                    if not evaluator:
                        evaluator_id = generate_unique_evaluator_id(db)
                        evaluator = Evaluator(
                            evaluator_id=evaluator_id,
                            organization_id=organization_id,
                            agent_id=UUID(agent_id),
                            persona_id=UUID(persona_id),
                            scenario_id=UUID(scenario_id),
                            tags=["auto-created", "test-voice-agent"]
                        )
                        db.add(evaluator)
                        db.commit()
                        db.refresh(evaluator)
                    
                    scenario = db.query(Scenario).filter(Scenario.id == UUID(scenario_id)).first()
                    scenario_name = scenario.name if scenario else "Unknown Scenario"
                    
                    # Generate result_id
                    max_attempts = 100
                    for _ in range(max_attempts):
                        candidate_id = f"{random.randint(100000, 999999)}"
                        existing = db.query(EvaluatorResult).filter(EvaluatorResult.result_id == candidate_id).first()
                        if not existing:
                            result_id = candidate_id
                            break
                except Exception as e:
                    logger.error(f"Error creating evaluator/result_id after bot run: {e}")
            
            # Create evaluator result for all test calls (with or without persona/scenario)
            # evaluator_id is optional - can be None if no persona/scenario
            if result_id and agent_id:
                try:
                    from app.models.database import EvaluatorResult, EvaluatorResultStatus
                    from app.workers.celery_app import process_evaluator_result_task
                    
                    # Determine name for the result
                    if scenario_name and scenario_name != "Test Call":
                        result_name = scenario_name
                    elif agent:
                        result_name = f"Test Call - {agent.name}"
                    else:
                        result_name = "Test Call"
                    
                    logger.info(f"Creating evaluator result: result_id={result_id}, agent_id={agent_id}, persona_id={persona_id}, scenario_id={scenario_id}, s3_key={call_metadata.get('s3_key')}")
                    
                    # Create evaluator result with QUEUED status
                    # persona_id and scenario_id can be None for test calls without persona/scenario
                    evaluator_result = EvaluatorResult(
                        result_id=result_id,
                        organization_id=organization_id,
                        evaluator_id=evaluator.id if evaluator else None,  # Optional
                        agent_id=UUID(agent_id),
                        persona_id=UUID(persona_id) if persona_id else None,  # Optional
                        scenario_id=UUID(scenario_id) if scenario_id else None,  # Optional
                        name=result_name,
                        duration_seconds=call_metadata.get("duration"),
                        status=EvaluatorResultStatus.QUEUED.value,  # Use .value to get the string
                        audio_s3_key=call_metadata.get("s3_key")
                    )
                    db.add(evaluator_result)
                    db.commit()
                    db.refresh(evaluator_result)
                    
                    logger.info(f"✅ Evaluator result created in database: id={evaluator_result.id}, result_id={result_id}")
                    
                    # Trigger Celery task
                    try:
                        logger.info(f"Triggering Celery task for evaluator result: {evaluator_result.id}")
                        
                        # Check if Celery app is properly configured
                        from app.workers.celery_app import celery_app
                        logger.info(f"Celery broker URL: {celery_app.conf.broker_url}")
                        logger.info(f"Celery result backend: {celery_app.conf.result_backend}")
                        
                        # Verify task is registered
                        if 'process_evaluator_result' not in celery_app.tasks:
                            logger.error("❌ Task 'process_evaluator_result' is not registered in Celery app!")
                            logger.error(f"Available tasks: {list(celery_app.tasks.keys())}")
                        else:
                            logger.info("✅ Task 'process_evaluator_result' is registered")
                        
                        task = process_evaluator_result_task.delay(str(evaluator_result.id))
                        logger.info(f"✅ Celery task triggered: task_id={task.id}, task_state={task.state}")
                        
                        # Try to get task info to verify it was queued
                        try:
                            task_info = task.info
                            logger.info(f"Task info: {task_info}")
                        except Exception as info_error:
                            logger.warning(f"Could not get task info (this is normal for async tasks): {info_error}")
                        
                        evaluator_result.celery_task_id = task.id
                        db.commit()
                        logger.info(f"✅ Updated evaluator result with celery_task_id: {task.id}")
                    except Exception as task_error:
                        logger.error(f"❌ Failed to trigger Celery task: {task_error}", exc_info=True)
                        # Still log that we created the result even if task trigger failed
                        logger.warning(f"Evaluator result {result_id} created but Celery task was not triggered. Task may need to be triggered manually.")
                        logger.warning(f"Please ensure Celery worker is running: celery -A app.workers.celery_app worker --loglevel=info")
                    
                    logger.info(f"✅ Created evaluator result {result_id} and triggered processing task")
                except Exception as e:
                    logger.error(f"❌ Error creating evaluator result: {e}", exc_info=True)
        
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
    voice_bundle = None
    use_voice_bundle_pipeline = False
    
    if agent_id:
        try:
            from app.models.database import Agent, VoiceBundle
            agent_uuid = UUID(agent_id)
            agent = db.query(Agent).filter(
                Agent.id == agent_uuid,
                Agent.organization_id == organization_id
            ).first()
            
            # Check if agent has a voice bundle (stt_llm_tts type)
            if agent and agent.voice_bundle_id:
                voice_bundle = db.query(VoiceBundle).filter(
                    VoiceBundle.id == agent.voice_bundle_id,
                    VoiceBundle.organization_id == organization_id
                ).first()
                if voice_bundle and voice_bundle.bundle_type == "stt_llm_tts":
                    use_voice_bundle_pipeline = True
                    print(f"[BACKEND] ✅ Using custom voice bundle: {voice_bundle.name}")
            
            if agent and agent.ai_provider_id:
                ai_provider = db.query(AIProvider).filter(
                    AIProvider.id == agent.ai_provider_id,
                    AIProvider.organization_id == organization_id,
                    AIProvider.is_active == True
                ).first()
        except ValueError:
            pass
    
    # For custom voice bundles (stt_llm_tts), we don't need a Google provider
    # The voice bundle has its own STT/LLM/TTS providers configured
    if not use_voice_bundle_pipeline:
        # Fall back to Google AI Provider if no agent-specific provider found (needed for S2S/Gemini path)
        if not ai_provider:
            from sqlalchemy import func
            google_value = ModelProvider.GOOGLE.value
            ai_provider = db.query(AIProvider).filter(
                AIProvider.organization_id == organization_id,
                AIProvider.provider == google_value,
                AIProvider.is_active == True
            ).first()
            # If not found, try case-insensitive match
            if not ai_provider:
                ai_provider = db.query(AIProvider).filter(
                    AIProvider.organization_id == organization_id,
                    func.lower(AIProvider.provider) == google_value.lower(),
                    AIProvider.is_active == True
                ).first()
        
        if not ai_provider:
            print("[BACKEND] ❌ AI Provider not configured")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="AI Provider not configured. Please configure an AI Provider in AI Providers settings or select one when creating the agent."
            )
        
        provider_val = ai_provider.provider.value if hasattr(ai_provider.provider, 'value') else ai_provider.provider
        print(f"[BACKEND] ✅ AI Provider found: {provider_val}")
    else:
        # For voice bundle pipeline, verify the required providers are configured
        from sqlalchemy import func
        missing_providers = []
        
        def check_provider(provider_enum):
            """Check if a provider is configured (either as AIProvider or Integration)."""
            if not provider_enum:
                return True  # Not required
            
            provider_value = provider_enum.value if hasattr(provider_enum, 'value') else str(provider_enum)
            
            # Check AIProvider
            found = db.query(AIProvider).filter(
                AIProvider.organization_id == organization_id,
                AIProvider.is_active == True,
            ).filter(
                (AIProvider.provider == provider_value) | 
                (func.lower(AIProvider.provider) == provider_value.lower())
            ).first()
            
            if found:
                return True
            
            # Check Integration for Deepgram and Cartesia
            platform_map = {
                'deepgram': IntegrationPlatform.DEEPGRAM,
                'cartesia': IntegrationPlatform.CARTESIA,
            }
            plat = platform_map.get(provider_value.lower())
            if plat:
                plat_value = plat.value if hasattr(plat, 'value') else plat
                found = db.query(Integration).filter(
                    Integration.organization_id == organization_id,
                    Integration.is_active == True,
                ).filter(
                    (Integration.platform == plat_value) | 
                    (func.lower(Integration.platform) == plat_value.lower())
                ).first()
                if found:
                    return True
            
            return False
        
        # Check required providers for the voice bundle
        if voice_bundle.stt_provider and not check_provider(voice_bundle.stt_provider):
            missing_providers.append(f"STT: {voice_bundle.stt_provider}")
        if voice_bundle.llm_provider and not check_provider(voice_bundle.llm_provider):
            missing_providers.append(f"LLM: {voice_bundle.llm_provider}")
        if voice_bundle.tts_provider and not check_provider(voice_bundle.tts_provider):
            missing_providers.append(f"TTS: {voice_bundle.tts_provider}")
        
        if missing_providers:
            print(f"[BACKEND] ❌ Missing providers for voice bundle: {missing_providers}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing AI providers for voice bundle: {', '.join(missing_providers)}. Please configure them in Integrations settings."
            )
        
        print(f"[BACKEND] ✅ Voice bundle providers configured")
    
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

