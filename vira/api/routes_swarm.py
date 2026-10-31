"""Swarm dashboard API: state snapshot, live SSE stream, topic injection."""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from vira.swarm.hub import get_hub


class InjectRequest(BaseModel):
    text: str
    author: str = "human"


def build_swarm_router(auth_dep=None) -> APIRouter:
    deps = [Depends(auth_dep)] if auth_dep else []
    router = APIRouter(prefix="/api/swarm", dependencies=deps)
    hub = get_hub()

    @router.get("/state")
    async def state(since: int = 0, limit: int = 400):
        return hub.state(since=since, limit=min(limit, 2000))

    @router.get("/stream")
    async def stream(since: Optional[int] = None):
        q = hub.subscribe()

        async def gen():
            try:
                yield "retry: 3000\n\n"
                while True:
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=15)
                        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                hub.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.post("/inject")
    async def inject(body: InjectRequest):
        if not body.text.strip():
            raise HTTPException(400, "text is empty")
        try:
            await hub.inject(body.text.strip(), body.author.strip()[:30] or "human")
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        return {"ok": True}

    return router
