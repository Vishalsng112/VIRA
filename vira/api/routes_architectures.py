"""Agent architecture catalog and paper-based selection API."""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from vira.agent.architectures import (
    ARCHITECTURE_PROFILES,
    TaskProfile,
    recommend_architecture,
)


class TaskProfileRequest(BaseModel):
    decomposability: float = Field(0.5, ge=0.0, le=1.0)
    sequential_dependencies: float = Field(0.5, ge=0.0, le=1.0)
    tool_count: int = Field(0, ge=0, le=10000)
    single_agent_baseline: Optional[float] = Field(None, ge=0.0, le=1.0)
    dynamic_environment: bool = False
    needs_peer_review: bool = False


def build_architecture_router(user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/agent-architectures")
    async def list_architectures(user=Depends(user_dep)):
        """Return the supported topologies and their measured coordination costs."""
        return {
            "architectures": [
                {"id": architecture.value, **profile}
                for architecture, profile in ARCHITECTURE_PROFILES.items()
            ]
        }

    @router.post("/agent-architectures/recommend")
    async def recommend(body: TaskProfileRequest, user=Depends(user_dep)):
        """Recommend a topology from measurable task properties."""
        profile = TaskProfile(**body.model_dump())
        return recommend_architecture(profile).as_dict()

    return router
