"""
Chat/Inference API Routes
For generating responses from AI models
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Dict, Optional
from uuid import UUID
from pydantic import BaseModel

from app.dependencies import get_db, get_organization_id
from app.services.llm_service import llm_service
from app.models.schemas import ModelProvider

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str  # "user", "assistant", "system"
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    provider: ModelProvider
    model: str
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None


class ChatResponse(BaseModel):
    text: str
    model: str
    usage: Optional[Dict[str, int]] = None
    processing_time: Optional[float] = None


@router.post("/completion", response_model=ChatResponse)
async def chat_completion(
    request: ChatRequest,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Generate a chat completion using the specified AI provider and model."""
    try:
        # Convert ChatMessage to dict format expected by LLM service
        messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        
        result = llm_service.generate_response(
            messages=messages,
            llm_provider=request.provider,
            llm_model=request.model,
            organization_id=organization_id,
            db=db,
            temperature=request.temperature,
            max_tokens=request.max_tokens
        )
        
        return ChatResponse(
            text=result.get("text", ""),
            model=result.get("model", request.model),
            usage=result.get("usage"),
            processing_time=result.get("processing_time")
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate response: {str(e)}"
        )

