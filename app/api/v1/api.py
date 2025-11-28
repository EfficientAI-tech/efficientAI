"""API v1 router aggregation."""

from fastapi import APIRouter
from app.api.v1.routes import (
    auth, audio, evaluations, results, batch, agents, personas, scenarios, iam,
    profile, integrations, data_sources, voicebundles, aiproviders, model_config,
    manual_evaluations, test_agents, conversation_evaluations, voice_agent
)

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
api_router.include_router(iam.router)
api_router.include_router(profile.router)
api_router.include_router(integrations.router)
api_router.include_router(data_sources.router)
api_router.include_router(voicebundles.router)
api_router.include_router(aiproviders.router)
api_router.include_router(model_config.router)
api_router.include_router(manual_evaluations.router)
api_router.include_router(test_agents.router)
api_router.include_router(conversation_evaluations.router)
api_router.include_router(voice_agent.router)

