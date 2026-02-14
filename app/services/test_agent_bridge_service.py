"""
Test Agent Bridge Service

Bridges test voice AI agent (voice bundle) with configured Voice AI agent via integration API.
"""

import asyncio
import tempfile
import os
import time
from typing import Dict, Any, Optional
from uuid import UUID
from loguru import logger

from app.models.database import Agent, Integration, VoiceBundle, EvaluatorResult, EvaluatorResultStatus
from app.core.encryption import decrypt_api_key
from app.services.voice_providers import get_voice_provider
from app.services.s3_service import s3_service
from app.workers.celery_app import process_evaluator_result_task


class TestAgentBridgeService:
    """Service to bridge test voice AI agent with Voice AI agent."""
    
    def __init__(self):
        """Initialize the bridge service."""
        pass
    
    async def bridge_test_agent_to_voice_agent(
        self,
        evaluator_id: UUID,
        evaluator_result_id: UUID,
        organization_id: UUID,
        db,
    ) -> Dict[str, Any]:
        """
        Main bridging logic to connect test agent to Voice AI agent.
        
        Args:
            evaluator_id: Evaluator ID
            evaluator_result_id: EvaluatorResult ID (pre-created)
            organization_id: Organization ID
            db: Database session
            
        Returns:
            Dictionary with call metadata including s3_key, duration, etc.
        """
        logger.info(
            f"[Bridge] Starting bridge_test_agent_to_voice_agent: "
            f"evaluator_id={evaluator_id}, result_id={evaluator_result_id}"
        )
        
        from app.models.database import Evaluator, Persona, Scenario
        
        # Load evaluator and related entities
        evaluator = db.query(Evaluator).filter(Evaluator.id == evaluator_id).first()
        if not evaluator:
            raise ValueError(f"Evaluator {evaluator_id} not found")
        
        agent = db.query(Agent).filter(Agent.id == evaluator.agent_id).first()
        if not agent:
            raise ValueError(f"Agent {evaluator.agent_id} not found")
        
        persona = db.query(Persona).filter(Persona.id == evaluator.persona_id).first()
        if not persona:
            raise ValueError(f"Persona {evaluator.persona_id} not found")
        
        scenario = db.query(Scenario).filter(Scenario.id == evaluator.scenario_id).first()
        if not scenario:
            raise ValueError(f"Scenario {evaluator.scenario_id} not found")
        
        # Verify agent has both voice_bundle_id and voice_ai_integration_id
        if not agent.voice_bundle_id:
            raise ValueError(f"Agent {agent.id} does not have voice_bundle_id configured")
        
        if not agent.voice_ai_integration_id or not agent.voice_ai_agent_id:
            raise ValueError(
                f"Agent {agent.id} does not have voice_ai_integration_id and voice_ai_agent_id configured"
            )
        
        # Get voice bundle
        voice_bundle = db.query(VoiceBundle).filter(
            VoiceBundle.id == agent.voice_bundle_id,
            VoiceBundle.organization_id == organization_id
        ).first()
        if not voice_bundle:
            raise ValueError(f"VoiceBundle {agent.voice_bundle_id} not found")
        
        # Get integration
        integration = db.query(Integration).filter(
            Integration.id == agent.voice_ai_integration_id,
            Integration.organization_id == organization_id,
            Integration.is_active == True
        ).first()
        if not integration:
            raise ValueError(f"Integration {agent.voice_ai_integration_id} not found or inactive")
        
        # Decrypt API key
        try:
            api_key = decrypt_api_key(integration.api_key)
        except Exception as e:
            raise ValueError(f"Failed to decrypt integration API key: {e}")
        
        # Get voice provider
        # Handle platform being either enum or string
        platform_value = integration.platform.value if hasattr(integration.platform, 'value') else integration.platform
        try:
            provider_class = get_voice_provider(platform_value)
            # For Vapi, pass the public_key as well (needed for web call creation)
            if platform_value.lower() == "vapi":
                logger.info(f"[Bridge] Creating Vapi provider with public_key={'set' if integration.public_key else 'NOT SET (will fail!)'}")
                provider = provider_class(api_key=api_key, public_key=integration.public_key)
            else:
                provider = provider_class(api_key=api_key)
        except ValueError as e:
            raise ValueError(f"Unsupported voice provider platform: {platform_value}")
        
        logger.info(
            f"[Bridge] Starting bridge for evaluator {evaluator.evaluator_id}, "
            f"agent {agent.name}, integration {platform_value}"
        )
        
        # Step 1: Create web call to Voice AI agent (Retell/Vapi)
        logger.info(f"[Bridge] Step 1: Creating web call to {platform_value} agent {agent.voice_ai_agent_id}")
        try:
            logger.info(f"[Bridge] Calling provider.create_web_call()...")
            web_call_response = provider.create_web_call(
                agent_id=agent.voice_ai_agent_id,
                metadata={
                    "evaluator_id": str(evaluator.id),
                    "evaluator_result_id": str(evaluator_result_id),
                    "organization_id": str(organization_id),
                    "test_agent_mode": True,
                    "persona_id": str(persona.id),
                    "scenario_id": str(scenario.id),
                }
            )
            logger.info(f"[Bridge] provider.create_web_call() returned: {list(web_call_response.keys()) if web_call_response else 'None'}")
            
            call_id = web_call_response.get("call_id")
            # For Retell: access_token (LiveKit token)
            # For Vapi: web_call_url (Daily.co URL) - we pass it in the access_token field
            access_token = web_call_response.get("access_token") or web_call_response.get("web_call_url")
            sample_rate = web_call_response.get("sample_rate", 24000)
            
            logger.info(f"[Bridge] Extracted: call_id={call_id}, access_token={'set' if access_token else 'NOT SET'}, sample_rate={sample_rate}")
            
            if not call_id:
                logger.error(f"[Bridge] ❌ No call_id in response. Full response: {web_call_response}")
                raise ValueError("No call_id received from web call creation")
            
            if not access_token:
                logger.error(f"[Bridge] ❌ No access_token/web_call_url in response. Full response: {web_call_response}")
                raise ValueError("No access_token/web_call_url received from web call creation")
            
            logger.info(f"[Bridge] ✅ Created web call: call_id={call_id}, token/url={'***' if access_token else 'None'}")
            
            # Step 2: Store call info in evaluator result and update status
            logger.info(f"[Bridge] Step 2: Updating evaluator result status to CALL_INITIATING")
            result = db.query(EvaluatorResult).filter(EvaluatorResult.id == evaluator_result_id).first()
            if not result:
                raise ValueError(f"EvaluatorResult {evaluator_result_id} not found")
            
            result.status = EvaluatorResultStatus.CALL_INITIATING.value
            result.call_event = "call_initiating"
            result.provider_call_id = call_id
            # Clear any previous error message
            result.error_message = None
            db.commit()
            logger.info(f"[Bridge] ✅ Status updated to CALL_INITIATING for result {result.result_id}: call_id={call_id}")
            
            # Step 3: Connect to Retell via WebRTC and run the bridge
            # This runs synchronously and waits for the call to complete
            logger.info(f"[Bridge] Initiating WebRTC bridge connection")
            
            # Run the WebRTC bridge - this will wait for the call to complete
            # The bridge handles:
            # 1. Connecting to Retell via LiveKit
            # 2. Bridging audio to/from test agent
            # 3. Recording the conversation
            # 4. Detecting call end
            bridge_task = asyncio.create_task(
                self._connect_and_bridge_with_webrtc(
                    evaluator_id=evaluator.id,
                    agent_id=agent.id,
                    persona_id=persona.id,
                    scenario_id=scenario.id,
                    organization_id=organization_id,
                    call_id=call_id,
                    access_token=access_token,
                    sample_rate=sample_rate,
                    provider_platform=platform_value,
                    evaluator_result_id=evaluator_result_id,
                    voice_bundle_id=agent.voice_bundle_id,
                    db=db
                )
            )
            
            # Step 4: Start polling for call results (runs concurrently with bridge)
            poll_task = asyncio.create_task(
                self._poll_call_results(
                    call_id=call_id,
                    provider=provider,
                    provider_platform=platform_value,
                    evaluator_result_id=evaluator_result_id,
                    organization_id=organization_id,
                    db=db
                )
            )
            
            logger.info(
                f"[Bridge] Call initiated: call_id={call_id}. "
                f"Waiting for bridge connection and call to complete..."
            )
            
            # Wait for both tasks to complete
            # The bridge task will complete when the call ends (WebRTC disconnect)
            # The poll task will complete when it gets results from voice provider and triggers evaluation
            # IMPORTANT: We must wait for BOTH tasks because:
            # - bridge_task detects call end via WebRTC (fast)
            # - poll_task fetches results from voice provider API and triggers evaluation (needs time)
            try:
                # Wait for bridge task first (it detects call end)
                # Give poll task additional time to fetch results after bridge completes
                logger.info(f"[Bridge] Waiting for bridge task to complete...")
                
                try:
                    await asyncio.wait_for(bridge_task, timeout=600)  # 10 minute max call duration
                    logger.info(f"[Bridge] Bridge task completed for call {call_id}")
                except asyncio.TimeoutError:
                    logger.warning(f"[Bridge] Bridge task timed out for call {call_id}")
                    bridge_task.cancel()
                except Exception as bridge_error:
                    logger.error(f"[Bridge] Bridge task error: {bridge_error}")
                
                # Now wait for poll task to finish fetching results and triggering evaluation
                # Give it extra time after bridge completes (Retell API may need time)
                logger.info(f"[Bridge] Waiting for poll task to fetch results and trigger evaluation...")
                
                try:
                    # Give poll task up to 2 minutes to fetch results after call ends
                    await asyncio.wait_for(poll_task, timeout=120)
                    logger.info(f"[Bridge] Poll task completed for call {call_id}")
                except asyncio.TimeoutError:
                    logger.warning(f"[Bridge] Poll task timed out for call {call_id}")
                    poll_task.cancel()
                except asyncio.CancelledError:
                    logger.info(f"[Bridge] Poll task was cancelled")
                except Exception as poll_error:
                    logger.error(f"[Bridge] Poll task error: {poll_error}")
                
                logger.info(f"[Bridge] All tasks completed for call {call_id}")
                
            except asyncio.TimeoutError:
                logger.warning(f"[Bridge] Call {call_id} timed out after 10 minutes")
                bridge_task.cancel()
                poll_task.cancel()
            
            return {
                "call_id": call_id,
                "access_token": access_token,
                "sample_rate": sample_rate,
                "web_call_response": web_call_response,
                "status": "completed",
                "message": "Call completed. Results should be available."
            }
            
        except Exception as e:
            logger.error(f"[Bridge] Error creating web call: {e}", exc_info=True)
            raise
    
    def initiate_voice_agent_call(
        self,
        provider,
        agent_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Initiate a call to Voice AI agent via integration API.
        
        Args:
            provider: Voice provider instance
            agent_id: Voice AI agent ID
            metadata: Optional metadata
            
        Returns:
            Call response with connection details
        """
        return provider.create_web_call(agent_id=agent_id, metadata=metadata or {})
    
    async def _connect_and_bridge_with_webrtc(
        self,
        evaluator_id: UUID,
        agent_id: UUID,
        persona_id: UUID,
        scenario_id: UUID,
        organization_id: UUID,
        call_id: str,
        access_token: str,
        sample_rate: int,
        provider_platform: str,
        evaluator_result_id: UUID,
        voice_bundle_id: UUID,
        db
    ):
        """
        Connect test agent via WebSocket and bridge to Retell/Vapi call using WebRTC.
        
        This implementation:
        1. Creates a WebRTC connection to Retell using call_id and access_token
        2. Connects test agent via WebSocket (voice bundle)
        3. Bridges audio streams bidirectionally
        4. Records the conversation
        
        Args:
            evaluator_id: Evaluator ID
            agent_id: Agent ID
            persona_id: Persona ID
            scenario_id: Scenario ID
            organization_id: Organization ID
            call_id: Retell/Vapi call ID
            access_token: Retell/Vapi access token
            sample_rate: Audio sample rate
            provider_platform: Platform name (retell, vapi)
            evaluator_result_id: EvaluatorResult ID
            voice_bundle_id: Voice bundle ID for test agent
            db: Database session
        """
        from app.services.webrtc_bridge.retell_webrtc_bridge import RetellWebRTCBridge
        from app.services.webrtc_bridge.vapi_webrtc_bridge import VapiWebRTCBridge
        from app.config import settings
        import websockets
        import json
        
        webrtc_bridge = None
        test_agent = None
        
        # Helper function to update status
        async def update_status(new_status: str, event: str = None, error: str = None):
            """Update evaluator result status."""
            from app.database import SessionLocal
            status_db = SessionLocal()
            try:
                result = status_db.query(EvaluatorResult).filter(
                    EvaluatorResult.id == evaluator_result_id
                ).first()
                if result:
                    result.status = new_status
                    if event:
                        result.call_event = event
                    if error:
                        result.error_message = error
                    status_db.commit()
                    logger.info(f"[Bridge WebRTC] Status updated: {new_status} (event: {event})")
            except Exception as e:
                logger.error(f"[Bridge WebRTC] Error updating status: {e}", exc_info=True)
            finally:
                status_db.close()
        
        try:
            logger.info(
                f"[Bridge WebRTC] Starting WebRTC bridge for evaluator {evaluator_id}, "
                f"bridging to {provider_platform} call {call_id}"
            )
            
            # Update status to connecting
            await update_status(
                EvaluatorResultStatus.CALL_CONNECTING.value,
                "call_connecting"
            )
            
            # Step 1: Create WebRTC bridge to Retell/Vapi
            # Set up call ended callback (shared between providers)
            async def on_call_ended():
                logger.info("[Bridge WebRTC] Call ended, cleaning up")
                await update_status(
                    EvaluatorResultStatus.CALL_ENDED.value,
                    "call_ended"
                )
                # Recording and result processing will be handled by polling
            
            if provider_platform == "retell":
                webrtc_bridge = RetellWebRTCBridge(
                    call_id=call_id,
                    access_token=access_token,
                    sample_rate=sample_rate
                )
                webrtc_bridge.on_call_ended = on_call_ended
                
                # Connect to Retell
                connected = await webrtc_bridge.connect_to_retell()
                if not connected:
                    await update_status(
                        EvaluatorResultStatus.FAILED.value,
                        "call_connection_failed",
                        "Failed to connect to Retell WebRTC call"
                    )
                    raise Exception("Failed to connect to Retell WebRTC call")
                
                logger.info("[Bridge WebRTC] ✅ Connected to Retell WebRTC call")
                
            elif provider_platform == "vapi":
                # For Vapi, access_token is actually the web_call_url (Daily.co URL)
                web_call_url = access_token  # Passed as access_token from bridge_test_agent_to_voice_agent
                
                webrtc_bridge = VapiWebRTCBridge(
                    call_id=call_id,
                    web_call_url=web_call_url,
                    sample_rate=sample_rate
                )
                webrtc_bridge.on_call_ended = on_call_ended
                
                # Connect to Vapi via Daily.co
                connected = await webrtc_bridge.connect_to_vapi()
                if not connected:
                    await update_status(
                        EvaluatorResultStatus.FAILED.value,
                        "call_connection_failed",
                        "Failed to connect to Vapi WebRTC call"
                    )
                    raise Exception("Failed to connect to Vapi WebRTC call")
                
                logger.info("[Bridge WebRTC] ✅ Connected to Vapi WebRTC call via Daily.co")
                
            else:
                raise ValueError(f"WebRTC bridging not yet implemented for platform: {provider_platform}")
            
            # Update status to in progress
            await update_status(
                EvaluatorResultStatus.CALL_IN_PROGRESS.value,
                "call_started"
            )
            
            # Step 2: Initialize in-process test agent (LLM + TTS)
            # This runs the test agent directly without WebSocket
            from app.services.webrtc_bridge.test_agent_processor import TestAgentProcessor, TestAgentConfig
            from app.models.database import Persona, Scenario, AIProvider, ModelProvider, Integration, IntegrationPlatform, Agent
            from app.core.encryption import decrypt_api_key
            
            # Load agent, persona and scenario for the test agent
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            persona = db.query(Persona).filter(Persona.id == persona_id).first()
            scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
            
            if not agent:
                raise ValueError(f"Agent not found: {agent_id}")
            if not persona or not scenario:
                raise ValueError(f"Persona or scenario not found")
            
            # Helper function to resolve API key (same logic as voice_agent.py + env fallback)
            def resolve_api_key_for_provider(provider: ModelProvider) -> str | None:
                """Resolve API key from AIProvider (preferred), Integration, or environment."""
                import os
                
                # 1) Check AIProvider table first (handle both string and enum comparisons)
                from sqlalchemy import func
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
                        key = decrypt_api_key(ai_provider_rec.api_key)
                        if key:
                            provider_val = provider.value if hasattr(provider, 'value') else provider
                            logger.debug(f"[Bridge WebRTC] Found API key for {provider_val} in AIProvider table")
                            return key
                    except Exception as e:
                        logger.error(f"[Bridge WebRTC] Failed to decrypt AIProvider key for {provider}: {e}")
                
                # 2) Check Integration table (for platforms that exist in IntegrationPlatform)
                platform_map = {
                    ModelProvider.DEEPGRAM: IntegrationPlatform.DEEPGRAM,
                    ModelProvider.CARTESIA: IntegrationPlatform.CARTESIA,
                    ModelProvider.ELEVENLABS: IntegrationPlatform.ELEVENLABS,
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
                            key = decrypt_api_key(integ.api_key)
                            if key:
                                provider_val = provider.value if hasattr(provider, 'value') else provider
                                logger.debug(f"[Bridge WebRTC] Found API key for {provider_val} in Integration table")
                                return key
                        except Exception as e:
                            logger.error(f"[Bridge WebRTC] Failed to decrypt Integration key for {provider}: {e}")
                
                # 3) Fallback to environment variables (same as voice_bundle.py)
                env_map = {
                    ModelProvider.OPENAI: "OPENAI_API_KEY",
                    ModelProvider.CARTESIA: "CARTESIA_API_KEY",
                    ModelProvider.DEEPGRAM: "DEEPGRAM_API_KEY",
                }
                env_var = env_map.get(provider)
                if env_var:
                    env_key = os.getenv(env_var)
                    if env_key:
                        provider_val = provider.value if hasattr(provider, 'value') else provider
                        logger.debug(f"[Bridge WebRTC] Found API key for {provider_val} in environment variable {env_var}")
                        return env_key
                
                return None
            
            # Get API keys for LLM (OpenAI) and TTS (Cartesia)
            logger.info(f"[Bridge WebRTC] Resolving API keys for test agent (org: {organization_id})")
            llm_api_key = resolve_api_key_for_provider(ModelProvider.OPENAI)
            tts_api_key = resolve_api_key_for_provider(ModelProvider.CARTESIA)
            
            # Log which keys were found
            logger.info(f"[Bridge WebRTC] API keys found: OpenAI={'yes' if llm_api_key else 'no'}, Cartesia={'yes' if tts_api_key else 'no'}")
            
            # Log which keys are missing for debugging
            missing_keys = []
            if not llm_api_key:
                missing_keys.append("OpenAI (LLM) - check AIProvider table or OPENAI_API_KEY env var")
            if not tts_api_key:
                missing_keys.append("Cartesia (TTS) - check Integration table or CARTESIA_API_KEY env var")
            
            if missing_keys:
                logger.warning(
                    f"[Bridge WebRTC] Missing API keys for test agent: {', '.join(missing_keys)}. "
                    f"Running without test agent."
                )
                test_agent = None
            else:
                # Build test agent config from persona/scenario
                # Extract goal from required_info or scenario description
                scenario_goal = "Complete the test call successfully"
                first_message = f"Hello, this is {persona.name} calling."
                
                if scenario.required_info:
                    # Check if required_info contains goal or first_message
                    if isinstance(scenario.required_info, dict):
                        scenario_goal = scenario.required_info.get("goal", scenario_goal)
                        first_message = scenario.required_info.get("first_message", first_message)
                
                # Build persona description from available fields
                # Persona model has: name, language, accent, gender, background_noise
                # Handle enum values being either enum or string
                persona_traits = []
                if hasattr(persona, 'gender') and persona.gender:
                    gender_val = persona.gender.value if hasattr(persona.gender, 'value') else persona.gender
                    persona_traits.append(f"{gender_val} caller")
                if hasattr(persona, 'accent') and persona.accent:
                    accent_val = persona.accent.value if hasattr(persona.accent, 'value') else persona.accent
                    persona_traits.append(f"with {accent_val} accent")
                if hasattr(persona, 'language') and persona.language:
                    language_val = persona.language.value if hasattr(persona.language, 'value') else persona.language
                    persona_traits.append(f"speaking {language_val}")
                
                persona_description = f"A caller named {persona.name}"
                if persona_traits:
                    persona_description += " (" + ", ".join(persona_traits) + ")"
                
                test_agent_config = TestAgentConfig(
                    # Who we are calling (the voice AI agent)
                    agent_name=agent.name or "Voice AI Agent",
                    agent_description=agent.description or "A voice AI assistant",
                    # Who we are pretending to be (the test caller)
                    persona_name=persona.name,
                    persona_description=persona_description,
                    # The test scenario
                    scenario_description=getattr(scenario, 'description', None) or scenario.name or "Test call scenario",
                    scenario_goal=scenario_goal,
                    first_message=first_message,
                    llm_api_key=llm_api_key,
                    tts_api_key=tts_api_key,
                    sample_rate=sample_rate,
                    max_turns=20
                )
                
                test_agent = TestAgentProcessor(test_agent_config)
                await test_agent.initialize()
                
                logger.info(f"[Bridge WebRTC] ✅ Test agent initialized: {persona.name}")
            
            # Step 3: Start recording and connect test agent to Retell
            webrtc_bridge.is_bridging = True
            
            # Start recording
            await webrtc_bridge.start_recording()
            
            logger.info("[Bridge WebRTC] ✅ Recording started")
            
            if test_agent:
                # Set up callbacks to connect test agent with voice provider
                # Vapi uses 40ms chunks (640 samples at 16kHz), Retell uses 20ms chunks
                chunk_ms = 40 if provider_platform == "vapi" else 20
                
                async def send_audio_chunks(audio: bytes):
                    """Stream audio to voice provider in real-time chunks."""
                    await test_agent.stream_audio_chunks(
                        audio,
                        webrtc_bridge.receive_audio_from_test_agent,
                        chunk_duration_ms=chunk_ms
                    )
                
                async def on_transcript_received(transcript: str):
                    """When voice agent finishes speaking, process with test agent."""
                    logger.info(f"[Bridge WebRTC] Received transcript from {provider_platform}: {transcript[:50]}...")
                    audio = await test_agent.process_agent_transcript(transcript)
                    if audio:
                        # Stream test agent's response audio to voice agent in chunks
                        logger.info(f"[Bridge WebRTC] Streaming {len(audio)} bytes of audio to {provider_platform}...")
                        await send_audio_chunks(audio)
                        logger.info("[Bridge WebRTC] Audio streaming complete")
                
                async def on_agent_start_talking():
                    """Voice AI agent started speaking -- test agent should wait."""
                    logger.info(f"[Bridge WebRTC] {provider_platform} agent started speaking")
                    test_agent.agent_is_talking = True

                async def on_agent_stop_talking():
                    """Voice AI agent stopped speaking -- test agent can respond."""
                    logger.info(f"[Bridge WebRTC] {provider_platform} agent stopped speaking")
                    test_agent.agent_is_talking = False
                    
                    # Process any transcript that was queued while agent was talking
                    pending = test_agent._pending_transcript
                    if pending:
                        test_agent._pending_transcript = None
                        logger.info(f"[Bridge WebRTC] Processing pending transcript after agent stopped: {pending[:50]}...")
                        audio = await test_agent.process_agent_transcript(pending)
                        if audio:
                            logger.info(f"[Bridge WebRTC] Streaming {len(audio)} bytes of audio to {provider_platform}...")
                            await send_audio_chunks(audio)
                            logger.info("[Bridge WebRTC] Audio streaming complete")

                async def on_call_should_end():
                    """Test agent decided to end the call."""
                    logger.info("[Bridge WebRTC] Test agent requested call end")
                    webrtc_bridge.is_bridging = False
                
                webrtc_bridge.on_transcript_received = on_transcript_received
                webrtc_bridge.on_agent_start_talking = on_agent_start_talking
                webrtc_bridge.on_agent_stop_talking = on_agent_stop_talking
                test_agent.on_call_should_end = on_call_should_end
                
                # Generate and send the first message to start the conversation
                logger.info("[Bridge WebRTC] Sending test agent's first message...")
                first_audio = await test_agent.generate_first_message()
                if first_audio:
                    logger.info(f"[Bridge WebRTC] Streaming first message ({len(first_audio)} bytes)...")
                    await send_audio_chunks(first_audio)
                    logger.info(f"[Bridge WebRTC] ✅ First message sent to {provider_platform}")
                
                logger.info("[Bridge WebRTC] ✅ Test agent connected, conversation starting...")
            else:
                logger.info("[Bridge WebRTC] Running without test agent - Retell will handle the call")
            
            # Wait for the call to end
            call_timeout = 300  # 5 minutes max call duration
            start_time = asyncio.get_event_loop().time()
            
            while webrtc_bridge.is_connected and webrtc_bridge.is_bridging:
                await asyncio.sleep(1)
                
                # Check for timeout
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > call_timeout:
                    logger.warning(f"[Bridge WebRTC] Call timeout after {call_timeout} seconds")
                    break
            
            logger.info("[Bridge WebRTC] Call ended")
            
            # Get conversation transcript from test agent (for debugging)
            if test_agent:
                conversation_log = test_agent.get_conversation_transcript()
                logger.info(f"[Bridge WebRTC] Test agent conversation log:\n{conversation_log}")
            
            # Stop local recording (for backup/debugging only)
            recording_path = await webrtc_bridge.stop_recording()
            if recording_path:
                logger.info(f"[Bridge WebRTC] Local recording saved: {recording_path}")
                # Clean up local file - we use voice provider's recording instead
                try:
                    if os.path.exists(recording_path):
                        os.remove(recording_path)
                        logger.info(f"[Bridge WebRTC] Local recording cleaned up (using {provider_platform}'s recording)")
                except Exception as e:
                    logger.warning(f"[Bridge WebRTC] Could not clean up local recording: {e}")
            
            logger.info(f"[Bridge WebRTC] Bridge completed. Waiting for _poll_call_results to fetch call data from {provider_platform}...")
            
            # NOTE: We do NOT upload to S3 or trigger transcription here.
            # The _poll_call_results task handles everything:
            # - Fetches call_data from voice provider (includes transcript, recording_url, cost, latency)
            # - Stores call_data in database
            # - Triggers evaluation task
            # This approach avoids:
            # - Redundant S3 storage costs
            # - Re-transcription (Retell already transcribed)
            
        except Exception as e:
            logger.error(f"[Bridge WebRTC] Error in WebRTC bridge: {e}", exc_info=True)
            
            # Update result status
            await update_status(
                EvaluatorResultStatus.FAILED.value,
                "call_error",
                str(e)
            )
        finally:
            # Cleanup
            if webrtc_bridge:
                await webrtc_bridge.disconnect()
            if test_agent:
                await test_agent.cleanup()
            
            logger.info("[Bridge WebRTC] Bridge cleanup completed")
    
    async def connect_test_agent(
        self,
        websocket_url: str,
        evaluator_id: UUID,
        persona_id: UUID,
        scenario_id: UUID,
        agent_id: UUID
    ) -> Any:
        """
        Connect test agent via WebSocket.
        
        Args:
            websocket_url: WebSocket URL for test agent
            evaluator_id: Evaluator ID
            persona_id: Persona ID
            scenario_id: Scenario ID
            agent_id: Agent ID
            
        Returns:
            WebSocket connection
        """
        # This would create a WebSocket connection
        # Implementation depends on the WebSocket client library used
        # For now, this is a placeholder
        logger.info(f"[Bridge] Connecting test agent via WebSocket: {websocket_url}")
        return None
    
    async def bridge_audio_streams(
        self,
        test_agent_ws: Any,
        voice_agent_call: Any
    ) -> None:
        """
        Bridge audio streams between test agent and voice agent.
        
        Args:
            test_agent_ws: Test agent WebSocket connection
            voice_agent_call: Voice AI agent call connection
        """
        # This would handle real-time audio bridging
        # Implementation would use audio streaming libraries
        logger.info("[Bridge] Bridging audio streams")
        pass
    
    async def _poll_call_results(
        self,
        call_id: str,
        provider,
        provider_platform: str,
        evaluator_result_id: UUID,
        organization_id: UUID,
        db,
        max_attempts: int = 120,  # Poll for up to 10 minutes (5 second intervals)
        poll_interval: int = 5
    ):
        """
        Poll for call results from the provider after call ends.
        
        Status Flow:
        - CALL_IN_PROGRESS (set by bridge) → CALL_ENDED → FETCHING_DETAILS → EVALUATING → COMPLETED
        
        This method uses the transcript directly from the provider (Retell/Vapi)
        instead of downloading audio to S3 and re-transcribing. This approach:
        - Avoids redundant S3 storage costs
        - Uses provider's high-quality transcription (with speaker diarization)
        - Enables faster evaluation since no transcription step is needed
        
        Args:
            call_id: Provider call ID
            provider: Voice provider instance
            provider_platform: Platform name (retell, vapi, etc.)
            evaluator_result_id: EvaluatorResult ID
            organization_id: Organization ID
            db: Database session
            max_attempts: Maximum polling attempts
            poll_interval: Seconds between polls
        """
        from app.database import SessionLocal
        
        # Use a new database session for polling (important for long-running task)
        poll_db = SessionLocal()
        try:
            result = poll_db.query(EvaluatorResult).filter(
                EvaluatorResult.id == evaluator_result_id
            ).first()
            
            if not result:
                logger.error(f"[Bridge Poll] EvaluatorResult {evaluator_result_id} not found")
                return
            
            # Store provider info immediately
            result.provider_call_id = call_id
            result.provider_platform = provider_platform
            poll_db.commit()
            logger.info(f"[Bridge Poll] Starting to poll {provider_platform} call {call_id} for results")
            
            # Wait a bit before starting to poll (call might be starting)
            await asyncio.sleep(10)
            
            call_completed = False
            call_metrics = None
            
            for attempt in range(max_attempts):
                try:
                    # Wait before polling (except first attempt)
                    if attempt > 0:
                        await asyncio.sleep(poll_interval)
                    
                    # Retrieve call metrics from provider
                    if provider_platform in ["retell", "vapi"] and hasattr(provider, "retrieve_call_metrics"):
                        call_metrics = provider.retrieve_call_metrics(call_id)
                    else:
                        logger.warning(f"[Bridge Poll] Platform {provider_platform} polling not yet implemented")
                        continue
                    
                    # Check call status
                    call_status = call_metrics.get("call_status", "")
                    end_timestamp = call_metrics.get("end_timestamp")
                    transcript = call_metrics.get("transcript", "")
                    
                    logger.info(
                        f"[Bridge Poll] Attempt {attempt + 1}: "
                        f"status={call_status}, has_end={bool(end_timestamp)}, "
                        f"transcript_len={len(transcript) if transcript else 0}"
                    )
                    
                    # If call is complete, process results
                    if end_timestamp or call_status in ["ended", "completed", "failed"]:
                        call_completed = True
                        logger.info(f"[Bridge Poll] ✅ Call completed: status={call_status}")
                        
                        # === Status: CALL_ENDED ===
                        result.status = EvaluatorResultStatus.CALL_ENDED.value
                        result.call_event = "call_ended"
                        poll_db.commit()
                        logger.info(f"[Bridge Poll] Status: CALL_ENDED")
                        
                        # === Status: FETCHING_DETAILS ===
                        result.status = EvaluatorResultStatus.FETCHING_DETAILS.value
                        poll_db.commit()
                        logger.info(f"[Bridge Poll] Status: FETCHING_DETAILS")
                        
                        # Store FULL call_data from provider
                        # This contains: transcript, transcript_object, recording_url, latency, cost, etc.
                        result.call_data = call_metrics
                        logger.info(f"[Bridge Poll] ✅ Stored call_data with {len(call_metrics)} keys: {list(call_metrics.keys())}")
                        
                        # Extract duration (Retell uses duration_ms, Vapi uses duration_seconds)
                        duration_ms = call_metrics.get("duration_ms")
                        duration_seconds = call_metrics.get("duration_seconds")
                        if duration_ms:
                            result.duration_seconds = duration_ms / 1000.0
                        elif duration_seconds:
                            result.duration_seconds = duration_seconds
                        if result.duration_seconds:
                            logger.info(f"[Bridge Poll] Duration: {result.duration_seconds:.1f}s")
                        
                        # Extract transcript and speaker segments
                        transcript_text, speaker_segments = self._extract_transcript_from_call_data(
                            call_metrics, provider_platform
                        )
                        
                        if transcript_text:
                            result.transcription = transcript_text
                            logger.info(f"[Bridge Poll] ✅ Extracted transcript: {len(transcript_text)} characters")
                        else:
                            logger.warning(f"[Bridge Poll] ⚠️ No transcript extracted from call_data")
                        
                        if speaker_segments:
                            result.speaker_segments = speaker_segments
                            logger.info(f"[Bridge Poll] ✅ Extracted {len(speaker_segments)} speaker segments")
                        
                        # Commit all the data
                        poll_db.commit()
                        logger.info(f"[Bridge Poll] ✅ All call data committed to database")
                        
                        # === Status: EVALUATING ===
                        if transcript_text:
                            result.status = EvaluatorResultStatus.EVALUATING.value
                            result.error_message = None
                            poll_db.commit()
                            logger.info(f"[Bridge Poll] Status: EVALUATING")
                            
                            # Trigger evaluation task (will skip transcription step since we have transcript)
                            try:
                                process_evaluator_result_task.delay(str(result.id))
                                logger.info(f"[Bridge Poll] ✅ Triggered evaluation task for result {result.id}")
                            except Exception as task_error:
                                logger.error(f"[Bridge Poll] ❌ Failed to trigger evaluation task: {task_error}", exc_info=True)
                                result.status = EvaluatorResultStatus.FAILED.value
                                result.error_message = f"Failed to trigger evaluation: {task_error}"
                                poll_db.commit()
                        else:
                            # No transcript - mark as failed
                            result.status = EvaluatorResultStatus.FAILED.value
                            result.error_message = "Call completed but no transcript available from provider"
                            poll_db.commit()
                            logger.warning(f"[Bridge Poll] ❌ No transcript in call_data")
                        
                        break
                    
                except Exception as e:
                    logger.warning(f"[Bridge Poll] Error on attempt {attempt + 1}: {e}")
                    continue
            
            if not call_completed:
                logger.warning(f"[Bridge Poll] ❌ Call {call_id} did not complete within polling window")
                result.status = EvaluatorResultStatus.FAILED.value
                result.error_message = "Call did not complete within expected time (10 min timeout)"
                poll_db.commit()
                
        except Exception as e:
            logger.error(f"[Bridge Poll] ❌ Fatal error in polling: {e}", exc_info=True)
            try:
                result = poll_db.query(EvaluatorResult).filter(
                    EvaluatorResult.id == evaluator_result_id
                ).first()
                if result:
                    result.status = EvaluatorResultStatus.FAILED.value
                    result.error_message = f"Polling error: {str(e)}"
                    poll_db.commit()
            except:
                pass
        finally:
            poll_db.close()
    
    def _extract_transcript_from_call_data(
        self, 
        call_data: dict, 
        provider_platform: str
    ) -> tuple[str, list[dict]]:
        """
        Extract transcript text and speaker segments from provider call data.
        
        Retell format:
        - transcript: Plain text transcript
        - transcript_object: List of {role, content, words: [{word, start, end}]}
        
        Args:
            call_data: Full call data from provider
            provider_platform: Provider name (retell, vapi, etc.)
            
        Returns:
            Tuple of (transcript_text, speaker_segments)
        """
        transcript_text = ""
        speaker_segments = []
        
        if provider_platform == "retell":
            # Get plain text transcript
            transcript_text = call_data.get("transcript", "")
            
            # Get structured transcript with speaker info
            transcript_object = call_data.get("transcript_object", [])
            
            if transcript_object:
                for msg in transcript_object:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    words = msg.get("words", [])
                    
                    # Map Retell roles to speaker labels
                    speaker = "Speaker 1" if role == "user" else "Speaker 2"
                    
                    # Calculate start/end times from words if available
                    start_time = 0.0
                    end_time = 0.0
                    if words:
                        start_time = words[0].get("start", 0.0)
                        end_time = words[-1].get("end", 0.0)
                    
                    if content.strip():
                        speaker_segments.append({
                            "speaker": speaker,
                            "text": content.strip(),
                            "start": start_time,
                            "end": end_time
                        })
                
                # If we have transcript_object but no plain transcript, build it
                if not transcript_text and speaker_segments:
                    transcript_text = "\n".join(
                        f"{seg['speaker']}: {seg['text']}" 
                        for seg in speaker_segments
                    )
        
        elif provider_platform == "vapi":
            # Vapi format:
            # - transcript: Plain text transcript (AI: ... \nUser: ...)
            # - transcript_object: List of {role, content, seconds_from_start, duration_ms, words}
            # - messages: Raw messages from Vapi
            transcript_text = call_data.get("transcript", "")
            
            # Get structured transcript object (preferred) or fall back to messages
            transcript_obj = call_data.get("transcript_object", [])
            messages = call_data.get("messages", [])
            
            # Use transcript_object if available (it's already cleaned up)
            if transcript_obj:
                for entry in transcript_obj:
                    role = entry.get("role", "unknown")
                    content = entry.get("content", "")
                    seconds_from_start = entry.get("seconds_from_start", 0)
                    duration_ms = entry.get("duration_ms", 0)
                    
                    # Map Vapi roles to speaker labels
                    if role == "user":
                        speaker = "Speaker 1"  # Test agent / caller
                    elif role == "agent":
                        speaker = "Speaker 2"  # Vapi agent
                    else:
                        continue
                    
                    if content and content.strip():
                        speaker_segments.append({
                            "speaker": speaker,
                            "text": content.strip(),
                            "start": seconds_from_start,
                            "end": seconds_from_start + (duration_ms / 1000) if duration_ms else seconds_from_start,
                            "words": entry.get("words")  # Word-level timing if available
                        })
            
            # Fall back to messages if no transcript_object
            elif messages:
                for msg in messages:
                    role = msg.get("role", "unknown")
                    content = msg.get("message", "") or msg.get("content", "")
                    seconds_from_start = msg.get("secondsFromStart", 0)
                    duration_ms = msg.get("duration", 0)
                    
                    # Skip system messages
                    if role == "system":
                        continue
                    
                    # Map Vapi roles to speaker labels
                    if role == "user":
                        speaker = "Speaker 1"  # Test agent / caller
                    elif role in ["bot", "assistant", "agent"]:
                        speaker = "Speaker 2"  # Vapi agent
                    else:
                        continue
                    
                    if content and content.strip():
                        speaker_segments.append({
                            "speaker": speaker,
                            "text": content.strip(),
                            "start": seconds_from_start,
                            "end": seconds_from_start + (duration_ms / 1000) if duration_ms else seconds_from_start
                        })
                
            # If we have segments but no plain transcript, build it
            if not transcript_text and speaker_segments:
                transcript_text = "\n".join(
                    f"{seg['speaker']}: {seg['text']}" 
                    for seg in speaker_segments
                )
        
        return transcript_text, speaker_segments
    
    def record_conversation(
        self,
        audio_data: bytes,
        organization_id: UUID,
        evaluator_id: UUID,
        result_id: str
    ) -> str:
        """
        Record the bridged conversation and upload to S3.
        
        Args:
            audio_data: Merged audio data
            organization_id: Organization ID
            evaluator_id: Evaluator ID
            result_id: Result ID
            
        Returns:
            S3 key of uploaded audio
        """
        import uuid
        file_id = uuid.uuid4()
        s3_key = s3_service.upload_file(
            file_content=audio_data,
            file_id=file_id,
            file_format="wav"
        )
        logger.info(f"[Bridge] Recorded conversation uploaded to S3: {s3_key}")
        return s3_key


# Singleton instance
test_agent_bridge_service = TestAgentBridgeService()

