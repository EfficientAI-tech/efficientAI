"""API v1 router aggregation."""

from fastapi import APIRouter
from app.api.v1.routes import auth, audio, evaluations, results, batch
from app.api.v1.routes import agents, personas, scenarios

api_router = APIRouter()

# Include all route routers
api_router.include_router(auth.router)
api_router.include_router(audio.router)
api_router.include_router(evaluations.router)
api_router.include_router(results.router)
api_router.include_router(batch.router)
api_router.include_router(agents.router)
api_router.include_router(personas.router)
api_router.include_router(scenarios.router)

