"""API v1 router aggregation."""

from fastapi import APIRouter
from app.api.v1.routes import auth, audio, evaluations, results, batch
from app.config import settings
from app.api.v1.routes import vaiops

api_router = APIRouter()

# Include all route routers
api_router.include_router(auth.router)
api_router.include_router(audio.router)
api_router.include_router(evaluations.router)
api_router.include_router(results.router)
api_router.include_router(batch.router)
api_router.include_router(vaiops.router)

