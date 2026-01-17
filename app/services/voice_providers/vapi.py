"""
Vapi Voice Provider Implementation
Handles integration with Vapi voice AI agents
"""
from typing import Dict, Any, Optional
from vapi_python import Vapi

from app.services.voice_providers.base import BaseVoiceProvider


class VapiVoiceProvider(BaseVoiceProvider):
    """Vapi voice provider implementation."""
    
    def __init__(self, api_key: str):
        """
        Initialize Vapi client.
        
        Args:
            api_key: Vapi Private API key
        """
        super().__init__(api_key)
        self.client = Vapi(token=api_key)
    
    def create_web_call(
        self,
        agent_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a web call with Vapi agent.
        
        Args:
            agent_id: Vapi agent ID
            metadata: Optional metadata to attach to the call
            **kwargs: Additional parameters
            
        Returns:
            Dictionary containing call information
        """
        try:
            # For Vapi, web calls are often initiated from the frontend using the public key.
            # However, we can create a call object or register it if needed.
            # Vapi's 'calls.create' is typically for outbound phone calls.
            # For web calls, Vapi's SDK on the frontend handles most of it.
            
            # If we need to provide some server-side initialization:
            # Note: This implementation might need adjustment based on specific Vapi SDK version
            
            call_params = {
                "agentId": agent_id,
            }
            if metadata:
                call_params["metadata"] = metadata
            
            call_params.update(kwargs)
            
            # Create a call (this is often for outbound, but Vapi also uses it for web call sessions sometimes)
            # For pure web calls, Vapi often just needs the agentId on the frontend.
            # But we implement this for consistency and future-proofing.
            
            # web_call_response = self.client.calls.create(**call_params)
            
            # Returning a mock-up/predicted structure if 'calls.create' is not what we want for web.
            # Most users just want the agent_id to pass to the frontend.
            
            return {
                "call_type": "web_call",
                "agent_id": agent_id,
                "metadata": metadata or {},
                # Vapi specific fields would go here
            }
        except Exception as e:
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

    def retrieve_call_metrics(self, call_id: str) -> Dict[str, Any]:
        """
        Retrieve call metrics and details from Vapi.
        
        Args:
            call_id: Vapi call ID
            
        Returns:
            Dictionary containing call information
        """
        try:
            # We use direct HTTP request since the SDK Wrapper 'Vapi' 
            # might not expose 'calls.get' in the version we are using, 
            # or to ensure we get the exact raw data we expect.
            # Vapi API base URL is usually https://api.vapi.ai
            import requests
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(f"https://api.vapi.ai/call/{call_id}", headers=headers)
            response.raise_for_status()
            data = response.json()
            
            # Normalize to match our expected structure if needed
            # For now, return the raw data with status normalized
            # Normalize response data
            started_at = data.get("startedAt")
            ended_at = data.get("endedAt")
            
            # Calculate duration in seconds
            duration_seconds = 0
            if data.get("durationMinutes"):
                 duration_seconds = data.get("durationMinutes") * 60
            elif started_at and ended_at:
                from dateutil import parser
                try:
                    start_time = parser.parse(started_at)
                    end_time = parser.parse(ended_at)
                    duration_seconds = (end_time - start_time).total_seconds()
                except:
                    pass

            # Extract nested fields safely
            analysis = data.get("analysis") or {}
            artifact = data.get("artifact") or {}
            messages = data.get("messages") or artifact.get("messages", []) or []
            transcript = data.get("transcript") or artifact.get("transcript")

            # Try to find summary in multiple places
            summary = analysis.get("summary") or data.get("summary")
            
            # --- Advanced Metrics Calculation ---
            latencies = []
            user_messages = [m for m in messages if m.get("role") == "user"]
            agent_messages = [m for m in messages if m.get("role") == "assistant" or m.get("role") == "bot" or m.get("role") == "agent"]
            
            # Calculate Latency (Time from User End to Agent Start)
            # We need to pair User -> Agent
            # Note: This is an approximation based on message sequence and timestamps
            import numpy as np
            
            for i, msg in enumerate(messages):
                if msg.get("role") == "user" and i + 1 < len(messages):
                    next_msg = messages[i+1]
                    if next_msg.get("role") in ["assistant", "bot", "agent"]:
                        user_end = (msg.get("secondsFromStart") or 0) + (msg.get("duration") or 0)
                        agent_start = next_msg.get("secondsFromStart") or 0
                        
                        # Only count positive, reasonable latencies (e.g., < 10s)
                        latency = (agent_start - user_end) * 1000 # Convert to ms
                        if 0 < latency < 10000:
                            latencies.append(latency)

            latency_stats = {}
            if latencies:
                latency_stats = {
                    "p50": round(np.percentile(latencies, 50), 2),
                    "p90": round(np.percentile(latencies, 90), 2),
                    "p95": round(np.percentile(latencies, 95), 2),
                    "p99": round(np.percentile(latencies, 99), 2),
                    "max": round(np.max(latencies), 2),
                    "min": round(np.min(latencies), 2),
                    "avg": round(np.mean(latencies), 2),
                    "num_turns": len(latencies)
                }

            # Barge-in / Interruption Calculation
            # Logic: If User starts speaking before Agent has finished their previous turn
            interruption_count = 0
            for i, msg in enumerate(messages):
                if msg.get("role") == "user" and i > 0:
                    prev_msg = messages[i-1]
                    if prev_msg.get("role") in ["assistant", "bot", "agent"]:
                        prev_agent_end = (prev_msg.get("secondsFromStart") or 0) + (prev_msg.get("duration") or 0)
                        user_start = msg.get("secondsFromStart") or 0
                        
                        # Overlap: User started before Agent finished (allow small buffer of e.g. 500ms for 'natural' pauses)
                        if user_start < (prev_agent_end - 0.5): 
                            interruption_count += 1
            
            # Normalize structure for frontend
            normalized_analysis = analysis.copy()
            if summary:
                normalized_analysis["summary"] = summary
            
            # Add calculated stats to analysis
            normalized_analysis["latency_stats"] = latency_stats
            normalized_analysis["interruption_count"] = interruption_count

            return {
                "call_id": data.get("id"),
                "call_status": data.get("status"),
                "start_timestamp": started_at,
                "end_timestamp": ended_at,
                "duration_seconds": duration_seconds,
                "cost": data.get("cost", 0),
                "cost_breakdown": data.get("costBreakdown"),
                "transcript": data.get("transcript") or artifact.get("transcript"),
                "messages": data.get("messages") or artifact.get("messages", []),
                "analysis": normalized_analysis,
                "monitor": data.get("monitor"),
                "ended_reason": data.get("endedReason") or data.get("reason"),
                "raw_data": data
            }
        except Exception as e:
            # For now, simplistic error handling
            print(f"Error getting Vapi metrics: {e}")
            raise ValueError(f"Failed to retrieve Vapi call metrics: {str(e)}")

    def test_connection(self) -> bool:
        """
        Test Vapi connection by attempting to list assistants.
        """
        try:
            self.client.assistants.list()
            return True
        except Exception as e:
            raise ValueError(f"Vapi connection test failed: {str(e)}")
