"""Mission API: start a mission from a brief, watch it live, browse/download the built project."""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from vira.mission.crew import MissionManager, get_manager
from vira.mission.workspace import WorkspaceError


class StartRequest(BaseModel):
    brief: str
    min_agents: Optional[int] = None
    max_agents: Optional[int] = None
    review_rounds: Optional[int] = None
    max_llm_calls: Optional[int] = None
    model: Optional[str] = None


class SayRequest(BaseModel):
    text: str
    to: str = "all"


def build_mission_router(auth_dep=None, manager: Optional[MissionManager] = None) -> APIRouter:
    deps = [Depends(auth_dep)] if auth_dep else []
    router = APIRouter(prefix="/api/mission", dependencies=deps)
    mgr = manager or get_manager()

    def live(mid: str):
        m = mgr.get(mid)
        if not m:
            raise HTTPException(404, "mission not running in this process (files of past missions are still readable)")
        return m

    @router.post("/start")
    async def start(body: StartRequest):
        try:
            dump = body.model_dump if hasattr(body, "model_dump") else body.dict      # pydantic v2 / v1
            m = await mgr.start(body.brief, **dump(exclude={"brief"}))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        except Exception as exc:                       # e.g. no LLM configured
            raise HTTPException(503, f"cannot start mission: {exc}")
        return {"id": m.id}

    @router.get("/list")
    async def list_missions():
        return {"missions": mgr.list()}

    @router.get("/{mid}/state")
    async def state(mid: str, since: int = 0):
        m = mgr.get(mid)
        if m:
            return {**m.snapshot(), **m.hub.state(since=since, limit=500), "live": not m.finished.is_set()}
        saved = mgr.saved(mid)
        if not saved:
            raise HTTPException(404, "unknown mission")
        return {**saved, "agents": [], "events": [], "last_seq": 0, "live": False}

    @router.get("/{mid}/stream")
    async def stream(mid: str):
        m = live(mid)
        q = m.hub.subscribe()

        async def gen():
            try:
                yield "retry: 3000\n\n"
                while True:
                    try:
                        yield f"data: {json.dumps(await asyncio.wait_for(q.get(), 15), ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                m.hub.unsubscribe(q)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.post("/{mid}/say")
    async def say(mid: str, body: SayRequest):
        if not body.text.strip():
            raise HTTPException(400, "text is empty")
        m = mgr.get(mid) or mgr.resume(mid)           # finished / pre-restart missions are re-opened for a revision
        if not m:
            raise HTTPException(404, "unknown mission")
        try:
            await m.say(body.text.strip(), body.to)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        return {"ok": True}

    @router.post("/{mid}/stop")
    async def stop(mid: str):
        live(mid).stop()
        return {"ok": True}

    @router.get("/{mid}/files")
    async def files(mid: str):
        ws = mgr.workspace(mid)
        if not ws:
            raise HTTPException(404, "unknown mission")
        return {"files": ws.files()}

    @router.get("/{mid}/file")
    async def file(mid: str, path: str):
        ws = mgr.workspace(mid)
        if not ws:
            raise HTTPException(404, "unknown mission")
        try:
            return {"path": path, "content": ws.read(path, limit=200_000)}
        except WorkspaceError as exc:
            raise HTTPException(404, str(exc))

    @router.get("/{mid}/download")
    async def download(mid: str):
        ws = mgr.workspace(mid)
        if not ws:
            raise HTTPException(404, "unknown mission")
        return Response(ws.zip_bytes(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{mid}.zip"'})

    return router
