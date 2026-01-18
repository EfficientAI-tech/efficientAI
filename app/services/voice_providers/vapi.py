"""
Vapi Voice Provider Implementation
Handles integration with Vapi voice AI agents
"""
from typing import Dict, Any, Optional
import requests
from loguru import logger

from app.services.voice_providers.base import BaseVoiceProvider

# Vapi API configuration
VAPI_API_URL = "https://api.vapi.ai"
VAPI_SAMPLE_RATE = 16000  # Vapi uses 16kHz audio


class VapiVoiceProvider(BaseVoiceProvider):
    """Vapi voice provider implementation."""
    
    def __init__(self, api_key: str, public_key: Optional[str] = None):
        """
        Initialize Vapi client.
        
        Args:
            api_key: Vapi Private API key (used for server-side operations like getting call metrics)
            public_key: Vapi Public API key (used for creating web calls)
        """
        super().__init__(api_key)
        self.public_key = public_key
        self.api_url = VAPI_API_URL
    
    def create_web_call(
        self,
        agent_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a web call with Vapi agent.
        
        Makes a POST request to Vapi's /call/web endpoint to create
        a web call session. Returns the call_id and webCallUrl (Daily.co URL)
        needed to connect to the call.
        
        NOTE: Vapi's /call/web endpoint requires the PUBLIC key, not the private key.
        
        Args:
            agent_id: Vapi assistant ID
            metadata: Optional metadata to attach to the call
            **kwargs: Additional parameters
            
        Returns:
            Dictionary containing:
                - call_id: Vapi call ID
                - web_call_url: Daily.co room URL for WebRTC connection
                - sample_rate: Audio sample rate (16000 for Vapi)
                - call_type: "web_call"
        """
        try:
            # Log the key configuration for debugging
            logger.info(f"[VapiProvider] create_web_call called - public_key={'set' if self.public_key else 'NOT SET'}, api_key={'set' if self.api_key else 'NOT SET'}")
            
            # Vapi's /call/web endpoint requires the PUBLIC key
            auth_key = self.public_key or self.api_key
            if not self.public_key:
                logger.warning("[VapiProvider] ⚠️ No public_key provided, using api_key. This WILL FAIL for /call/web endpoint!")
            
            if not auth_key:
                raise ValueError("No authentication key available (neither public_key nor api_key)")
            
            url = f"{self.api_url}/call/web"
            headers = {
                'Authorization': f'Bearer {auth_key}',
                'Content-Type': 'application/json'
            }
            
            # Build request payload
            payload = {
                'assistantId': agent_id,
            }
            
            # Add assistant overrides if provided
            if kwargs.get('assistant_overrides'):
                payload['assistantOverrides'] = kwargs['assistant_overrides']
            
            # Add metadata if provided
            if metadata:
                payload['metadata'] = metadata
            
            logger.info(f"[VapiProvider] Creating web call with assistant_id={agent_id}, url={url}")
            
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            # Log raw response for debugging
            logger.info(f"[VapiProvider] Response status: {response.status_code}")
            
            try:
                data = response.json()
            except Exception as json_err:
                logger.error(f"[VapiProvider] Failed to parse response JSON: {json_err}, raw: {response.text[:500]}")
                raise ValueError(f"Invalid JSON response from Vapi: {response.text[:200]}")
            
            if response.status_code == 201:
                call_id = data.get('id')
                web_call_url = data.get('webCallUrl')
                
                if not call_id:
                    logger.error(f"[VapiProvider] ❌ Response missing 'id' field. Response data: {data}")
                    raise ValueError(f"Vapi API returned success but no call ID. Response: {data}")
                
                if not web_call_url:
                    logger.warning(f"[VapiProvider] ⚠️ Response missing 'webCallUrl' field. Response data: {data}")
                
                logger.info(f"[VapiProvider] ✅ Web call created: call_id={call_id}, web_call_url={'set' if web_call_url else 'NOT SET'}")
                
                return {
                    "call_id": call_id,
                    "web_call_url": web_call_url,
                    "sample_rate": VAPI_SAMPLE_RATE,
                    "call_type": "web_call",
                    "agent_id": agent_id,
                    "metadata": metadata or {},
                    "raw_response": data
                }
            else:
                error_msg = data.get('message', f'Unknown error (status {response.status_code})')
                logger.error(f"[VapiProvider] ❌ Failed to create web call: {error_msg}, full response: {data}")
                raise ValueError(f"Vapi API error: {error_msg}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"[VapiProvider] Request error: {e}")
            raise ValueError(f"Failed to create Vapi web call: {str(e)}")
        except Exception as e:
            logger.error(f"[VapiProvider] Unexpected error: {e}")
            raise ValueError(f"Failed to create Vapi web call: {str(e)}")

    def create_agent(
        self,
        name: str,
        model: Dict[str, Any],
        voice: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a new Vapi agent.
        
        Args:
            name: Agent name
            model: Model configuration
            voice: Voice configuration
            **kwargs: Additional parameters
            
        Returns:
            Dictionary containing agent information
        """
        try:
            agent_params = {
                "name": name,
                "model": model,
                "voice": voice,
            }
            agent_params.update(kwargs)
            
            # agent_response = self.client.agents.create(**agent_params)
            
            # Placeholder until exact SDK call is confirmed
            return {"message": "Create agent not fully implemented for Vapi", "params": agent_params}
        except Exception as e:
            raise ValueError(f"Failed to create Vapi agent: {str(e)}")

    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        """
        Get Vapi agent details.
        
        Args:
            agent_id: Vapi agent ID
            
        Returns:
            Dictionary containing agent information
        """
        try:
            # agent_response = self.client.agents.get(agent_id)
            return {"agent_id": agent_id, "name": "Vapi Agent"}
        except Exception as e:
            raise ValueError(f"Failed to get Vapi agent: {str(e)}")

    def _make_json_serializable(self, obj: Any) -> Any:
        """
        Recursively convert NumPy types and other non-JSON-serializable types to native Python types.
        """
        import numpy as np
        
        if isinstance(obj, dict):
            return {k: self._make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_json_serializable(item) for item in obj]
        elif isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.bool_):
            return bool(obj)
        else:
            return obj

    def retrieve_call_metrics(self, call_id: str) -> Dict[str, Any]:
        """
        Retrieve call metrics and details from Vapi.
        
        Args:
            call_id: Vapi call ID
            
        Returns:
            Dictionary containing comprehensive call information including:
            - Basic call info (id, status, timestamps, duration)
            - Cost breakdown (transport, STT, LLM, TTS, Vapi fees)
            - Transcript (plain text and structured messages)
            - Analysis (summary, success evaluation)
            - Performance metrics (latencies, interruptions)
            - Recording URLs (mono, stereo, assistant, customer)
        """
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(f"{self.api_url}/call/{call_id}", headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Log raw response for debugging
            logger.info(f"[VapiProvider] Retrieved call {call_id}, status: {data.get('status')}, ended_reason: {data.get('endedReason')}")
            logger.debug(f"[VapiProvider] Raw call data keys: {list(data.keys())}")
            
            # Extract nested fields safely
            artifact = data.get("artifact") or {}
            analysis = data.get("analysis") or {}
            cost_breakdown = data.get("costBreakdown") or {}
            
            # Get transcript from multiple possible locations
            transcript = data.get("transcript") or artifact.get("transcript", "")
            
            # Get messages (structured conversation) from multiple possible locations
            messages = data.get("messages") or artifact.get("messages", []) or []
            
            # Filter out system messages for display (keep for raw_data)
            display_messages = [m for m in messages if m.get("role") != "system"]
            
            logger.info(f"[VapiProvider] Call {call_id}: transcript_len={len(transcript) if transcript else 0}, messages_count={len(display_messages)}")
            
            # Log end reason for debugging
            if data.get("endedReason"):
                logger.info(f"[VapiProvider] Call ended reason: {data.get('endedReason')}")
            
            # === Timestamps and Duration ===
            started_at = data.get("startedAt")
            ended_at = data.get("endedAt")
            
            duration_seconds = 0
            if started_at and ended_at:
                from dateutil import parser
                try:
                    start_time = parser.parse(started_at)
                    end_time = parser.parse(ended_at)
                    duration_seconds = (end_time - start_time).total_seconds()
                except Exception as e:
                    logger.warning(f"[VapiProvider] Failed to parse timestamps: {e}")

            # === Recording URLs ===
            recording = artifact.get("recording") or {}
            mono_recording = recording.get("mono") or {}
            
            recording_urls = {
                "combined_url": data.get("recordingUrl") or artifact.get("recordingUrl") or mono_recording.get("combinedUrl"),
                "stereo_url": data.get("stereoRecordingUrl") or artifact.get("stereoRecordingUrl") or recording.get("stereoUrl"),
                "assistant_url": mono_recording.get("assistantUrl"),
                "customer_url": mono_recording.get("customerUrl"),
            }

            # === Performance Metrics (from Vapi's artifact) ===
            perf_metrics = artifact.get("performanceMetrics") or {}
            turn_latencies = perf_metrics.get("turnLatencies") or []
            
            # Use Vapi's pre-calculated averages if available
            latency_stats = {}
            if perf_metrics:
                latency_stats = {
                    "model_latency_avg": perf_metrics.get("modelLatencyAverage"),
                    "voice_latency_avg": perf_metrics.get("voiceLatencyAverage"),
                    "transcriber_latency_avg": perf_metrics.get("transcriberLatencyAverage"),
                    "endpointing_latency_avg": perf_metrics.get("endpointingLatencyAverage"),
                    "turn_latency_avg": perf_metrics.get("turnLatencyAverage"),
                    "from_transport_latency_avg": perf_metrics.get("fromTransportLatencyAverage"),
                    "to_transport_latency_avg": perf_metrics.get("toTransportLatencyAverage"),
                    "num_assistant_interrupted": perf_metrics.get("numAssistantInterrupted", 0),
                    "turn_latencies": turn_latencies,
                }
            
            # Calculate additional latency percentiles if we have turn latencies
            if turn_latencies:
                import numpy as np
                total_latencies = [t.get("turnLatency", 0) for t in turn_latencies if t.get("turnLatency")]
                if total_latencies:
                    # Convert NumPy types to native Python types for JSON serialization
                    latency_stats.update({
                        "p50": float(round(np.percentile(total_latencies, 50), 2)),
                        "p90": float(round(np.percentile(total_latencies, 90), 2)),
                        "p95": float(round(np.percentile(total_latencies, 95), 2)),
                        "p99": float(round(np.percentile(total_latencies, 99), 2)),
                        "max": float(round(np.max(total_latencies), 2)),
                        "min": float(round(np.min(total_latencies), 2)),
                        "num_turns": int(len(total_latencies))
                    })

            # === Interruption Count ===
            interruption_count = perf_metrics.get("numAssistantInterrupted", 0)
            
            # If not provided by Vapi, calculate manually
            if not interruption_count and messages:
                for i, msg in enumerate(messages):
                    if msg.get("role") == "user" and i > 0:
                        prev_msg = messages[i-1]
                        if prev_msg.get("role") in ["assistant", "bot"]:
                            prev_agent_end = (prev_msg.get("secondsFromStart") or 0) + ((prev_msg.get("duration") or 0) / 1000)
                            user_start = msg.get("secondsFromStart") or 0
                            if user_start < (prev_agent_end - 0.5):
                                interruption_count += 1

            # === Cost Breakdown (detailed) ===
            analysis_cost = cost_breakdown.get("analysisCostBreakdown") or {}
            
            normalized_cost_breakdown = {
                "transport": cost_breakdown.get("transport", 0),
                "stt": cost_breakdown.get("stt", 0),
                "llm": cost_breakdown.get("llm", 0),
                "tts": cost_breakdown.get("tts", 0),
                "vapi": cost_breakdown.get("vapi", 0),
                "total": cost_breakdown.get("total", 0),
                # Token usage
                "llm_prompt_tokens": cost_breakdown.get("llmPromptTokens", 0),
                "llm_completion_tokens": cost_breakdown.get("llmCompletionTokens", 0),
                "llm_cached_prompt_tokens": cost_breakdown.get("llmCachedPromptTokens", 0),
                "tts_characters": cost_breakdown.get("ttsCharacters", 0),
                # Analysis costs
                "analysis": {
                    "summary": analysis_cost.get("summary", 0),
                    "success_evaluation": analysis_cost.get("successEvaluation", 0),
                    "structured_data": analysis_cost.get("structuredData", 0),
                },
            }

            # === Analysis (summary, success evaluation) ===
            summary = analysis.get("summary") or data.get("summary") or ""
            success_evaluation = analysis.get("successEvaluation")
            
            normalized_analysis = {
                "summary": summary,
                "success_evaluation": success_evaluation,
                "latency_stats": latency_stats,
                "interruption_count": interruption_count,
            }

            # === Build Transcript Object (structured with timing) ===
            # Filter to only user and bot messages for the transcript object
            transcript_object = []
            for msg in display_messages:
                role = msg.get("role", "unknown")
                content = msg.get("message", "") or msg.get("content", "")
                
                if not content or role == "system":
                    continue
                
                # Map roles for consistency
                if role in ["bot", "assistant"]:
                    normalized_role = "agent"
                elif role == "user":
                    normalized_role = "user"
                else:
                    continue
                
                transcript_entry = {
                    "role": normalized_role,
                    "content": content,
                    "seconds_from_start": msg.get("secondsFromStart", 0),
                    "duration_ms": msg.get("duration", 0),
                    "end_time_ms": msg.get("endTime"),
                    "time_ms": msg.get("time"),
                }
                
                # Include word-level confidence if available
                metadata = msg.get("metadata") or {}
                if metadata.get("wordLevelConfidence"):
                    transcript_entry["words"] = metadata["wordLevelConfidence"]
                
                transcript_object.append(transcript_entry)

            result = {
                "call_id": data.get("id"),
                "call_status": data.get("status"),
                "start_timestamp": started_at,
                "end_timestamp": ended_at,
                "duration_seconds": duration_seconds,
                "cost": data.get("cost", 0),
                "cost_breakdown": normalized_cost_breakdown,
                "transcript": transcript,
                "transcript_object": transcript_object,
                "messages": display_messages,
                "analysis": normalized_analysis,
                "recording_urls": recording_urls,
                "monitor": data.get("monitor"),
                "ended_reason": data.get("endedReason") or data.get("reason"),
                "metadata": data.get("metadata"),
                "assistant_id": data.get("assistantId"),
                "call_type": data.get("type"),
                "raw_data": data
            }
            
            # Ensure all values are JSON serializable (convert NumPy types, etc.)
            return self._make_json_serializable(result)
        except Exception as e:
            logger.error(f"[VapiProvider] Error getting call metrics: {e}", exc_info=True)
            raise ValueError(f"Failed to retrieve Vapi call metrics: {str(e)}")

    def test_connection(self) -> bool:
        """
        Test Vapi connection by attempting to list assistants via HTTP API.
        """
        try:
            url = f"{self.api_url}/assistant"
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return True
            elif response.status_code == 401:
                raise ValueError("Invalid API key")
            else:
                data = response.json()
                raise ValueError(f"API error: {data.get('message', 'Unknown error')}")
                
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Vapi connection test failed: {str(e)}")
        except Exception as e:
            raise ValueError(f"Vapi connection test failed: {str(e)}")
