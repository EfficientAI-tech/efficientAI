"""Conversation evaluation routes for evaluating manual transcriptions against agent objectives."""

import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app.database import get_db
from app.dependencies import get_api_key, get_organization_id
from app.models.database import ConversationEvaluation, ManualTranscription, Agent, ModelProvider
from app.models.schemas import ConversationEvaluationCreate, ConversationEvaluationResponse, MessageResponse
from app.services.llm_service import llm_service

router = APIRouter(prefix="/conversation-evaluations", tags=["Conversation Evaluations"])


@router.post("", response_model=ConversationEvaluationResponse, status_code=status.HTTP_201_CREATED, operation_id="createConversationEvaluation")
async def create_conversation_evaluation(
    request: ConversationEvaluationCreate,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Evaluate a manual transcription against an agent's objective.
    
    This endpoint uses an LLM to evaluate whether the conversation achieved its objective
    and provides additional metrics about the conversation quality.
    """
    # Get transcription
    transcription = db.query(ManualTranscription).filter(
        ManualTranscription.id == request.transcription_id,
        ManualTranscription.organization_id == organization_id
    ).first()
    
    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found"
        )
    
    # Get agent
    agent = db.query(Agent).filter(
        Agent.id == request.agent_id,
        Agent.organization_id == organization_id
    ).first()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    # Check if evaluation already exists
    existing = db.query(ConversationEvaluation).filter(
        ConversationEvaluation.transcription_id == request.transcription_id,
        ConversationEvaluation.agent_id == request.agent_id,
        ConversationEvaluation.organization_id == organization_id
    ).first()
    
    if existing:
        # Return existing evaluation
        return existing
    
    # Prepare LLM prompt for evaluation
    agent_objective = agent.description or f"The agent's objective is to handle {agent.call_type} calls for {agent.name}."
    
    evaluation_prompt = f"""You are evaluating a conversation transcript to determine if the agent achieved the conversation objective.

Agent Information:
- Name: {agent.name}
- Objective/Purpose: {agent_objective}
- Call Type: {agent.call_type}
- Language: {agent.language}

Conversation Transcript:
{transcription.transcript}

Please evaluate this conversation and provide:
1. A binary answer (true/false): Was the conversation objective achieved?
2. A brief reason for your answer
3. Additional metrics about the conversation quality:
   - Professionalism (0-1 scale)
   - Clarity (0-1 scale)
   - Empathy (0-1 scale, if applicable)
   - Problem Resolution (0-1 scale, if applicable)
   - Overall Quality (0-1 scale)
4. An overall score (0.0 to 1.0) representing how well the agent performed

Respond in JSON format with the following structure:
{{
    "objective_achieved": true/false,
    "objective_achieved_reason": "brief explanation",
    "additional_metrics": {{
        "professionalism": 0.0-1.0,
        "clarity": 0.0-1.0,
        "empathy": 0.0-1.0,
        "problem_resolution": 0.0-1.0,
        "overall_quality": 0.0-1.0
    }},
    "overall_score": 0.0-1.0
}}

Only respond with valid JSON, no additional text."""

    try:
        # Call LLM service
        llm_provider = request.llm_provider or ModelProvider.OPENAI
        llm_model = request.llm_model or "gpt-4o"
        
        messages = [
            {"role": "system", "content": "You are an expert conversation evaluator. Analyze conversations objectively and provide structured evaluations."},
            {"role": "user", "content": evaluation_prompt}
        ]
        
        llm_result = llm_service.generate_response(
            messages=messages,
            llm_provider=llm_provider,
            llm_model=llm_model,
            organization_id=organization_id,
            db=db,
            temperature=0.3,  # Lower temperature for more consistent evaluations
            max_tokens=1000
        )
        
        # Parse LLM response
        response_text = llm_result["text"].strip()
        
        # Try to extract JSON from response (handle cases where LLM adds markdown formatting)
        if response_text.startswith("```json"):
            response_text = response_text.replace("```json", "").replace("```", "").strip()
        elif response_text.startswith("```"):
            response_text = response_text.replace("```", "").strip()
        
        try:
            evaluation_data = json.loads(response_text)
        except json.JSONDecodeError:
            # If JSON parsing fails, try to extract JSON object from text
            import re
            json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
            if json_match:
                evaluation_data = json.loads(json_match.group())
            else:
                raise ValueError("Could not parse LLM response as JSON")
        
        # Extract evaluation results
        objective_achieved = bool(evaluation_data.get("objective_achieved", False))
        objective_achieved_reason = evaluation_data.get("objective_achieved_reason", "")
        additional_metrics = evaluation_data.get("additional_metrics", {})
        overall_score = float(evaluation_data.get("overall_score", 0.0))
        
        # Serialize LLM response to JSON-compatible format
        # Extract only the serializable parts, excluding the raw_response object
        serializable_llm_response = {
            "text": llm_result.get("text"),
            "model": llm_result.get("model"),
            "usage": llm_result.get("usage", {}),
            "processing_time": llm_result.get("processing_time"),
        }
        
        # Try to extract serializable parts from raw_response if it exists
        raw_response = llm_result.get("raw_response")
        if raw_response:
            try:
                # For OpenAI ChatCompletion objects, try to serialize
                if hasattr(raw_response, 'model_dump'):
                    # Pydantic v2 style
                    serializable_llm_response["raw_response"] = raw_response.model_dump()
                elif hasattr(raw_response, 'dict'):
                    # Pydantic v1 style
                    serializable_llm_response["raw_response"] = raw_response.dict()
                elif hasattr(raw_response, '__dict__'):
                    # Try using __dict__ but filter out non-serializable items
                    raw_dict = {}
                    for key, value in raw_response.__dict__.items():
                        try:
                            json.dumps(value)  # Test if serializable
                            raw_dict[key] = value
                        except (TypeError, ValueError):
                            raw_dict[key] = str(value)
                    serializable_llm_response["raw_response"] = raw_dict
                else:
                    # Manual extraction for OpenAI ChatCompletion
                    raw_dict = {}
                    if hasattr(raw_response, 'id'):
                        raw_dict["id"] = raw_response.id
                    if hasattr(raw_response, 'model'):
                        raw_dict["model"] = raw_response.model
                    if hasattr(raw_response, 'choices') and raw_response.choices:
                        raw_dict["choices"] = [
                            {
                                "index": choice.index if hasattr(choice, 'index') else None,
                                "message": {
                                    "role": choice.message.role if hasattr(choice, 'message') and hasattr(choice.message, 'role') else None,
                                    "content": choice.message.content if hasattr(choice, 'message') and hasattr(choice.message, 'content') else None,
                                } if hasattr(choice, 'message') else None,
                                "finish_reason": choice.finish_reason if hasattr(choice, 'finish_reason') else None,
                            }
                            for choice in raw_response.choices
                        ]
                    if hasattr(raw_response, 'usage') and raw_response.usage:
                        raw_dict["usage"] = {
                            "prompt_tokens": raw_response.usage.prompt_tokens if hasattr(raw_response.usage, 'prompt_tokens') else None,
                            "completion_tokens": raw_response.usage.completion_tokens if hasattr(raw_response.usage, 'completion_tokens') else None,
                            "total_tokens": raw_response.usage.total_tokens if hasattr(raw_response.usage, 'total_tokens') else None,
                        }
                    serializable_llm_response["raw_response"] = raw_dict
            except Exception as e:
                # If serialization fails, store minimal info
                serializable_llm_response["raw_response"] = {
                    "error": "Could not serialize raw response",
                    "type": type(raw_response).__name__,
                    "str": str(raw_response)[:500]  # First 500 chars
                }
        
        # Create evaluation record
        evaluation = ConversationEvaluation(
            organization_id=organization_id,
            transcription_id=request.transcription_id,
            agent_id=request.agent_id,
            objective_achieved=objective_achieved,
            objective_achieved_reason=objective_achieved_reason,
            additional_metrics=additional_metrics,
            overall_score=overall_score,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_response=serializable_llm_response
        )
        
        db.add(evaluation)
        db.commit()
        db.refresh(evaluation)
        
        return evaluation
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to evaluate conversation: {str(e)}"
        )


@router.get("", response_model=List[ConversationEvaluationResponse], operation_id="listConversationEvaluations")
async def list_conversation_evaluations(
    transcription_id: UUID = None,
    agent_id: UUID = None,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """List conversation evaluations, optionally filtered by transcription or agent."""
    query = db.query(ConversationEvaluation).filter(
        ConversationEvaluation.organization_id == organization_id
    )
    
    if transcription_id:
        query = query.filter(ConversationEvaluation.transcription_id == transcription_id)
    if agent_id:
        query = query.filter(ConversationEvaluation.agent_id == agent_id)
    
    evaluations = query.order_by(ConversationEvaluation.created_at.desc()).all()
    return evaluations


@router.get("/{evaluation_id}", response_model=ConversationEvaluationResponse, operation_id="getConversationEvaluation")
async def get_conversation_evaluation(
    evaluation_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Get a specific conversation evaluation."""
    evaluation = db.query(ConversationEvaluation).filter(
        ConversationEvaluation.id == evaluation_id,
        ConversationEvaluation.organization_id == organization_id
    ).first()
    
    if not evaluation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation not found"
        )
    
    return evaluation


@router.delete("/{evaluation_id}", response_model=MessageResponse, operation_id="deleteConversationEvaluation")
async def delete_conversation_evaluation(
    evaluation_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Delete a conversation evaluation."""
    evaluation = db.query(ConversationEvaluation).filter(
        ConversationEvaluation.id == evaluation_id,
        ConversationEvaluation.organization_id == organization_id
    ).first()
    
    if not evaluation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation not found"
        )
    
    db.delete(evaluation)
    db.commit()
    
    return {"message": "Evaluation deleted successfully"}

