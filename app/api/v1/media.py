"""Media-only API routes (live voice WebSockets)."""

from fastapi import APIRouter

from app.api.v1.routes import vobiz_telephony, voice_agent

media_router = APIRouter()
media_router.include_router(vobiz_telephony.webhook_router)
media_router.include_router(vobiz_telephony.carrier_ws_router)
media_router.include_router(voice_agent.ws_router)
