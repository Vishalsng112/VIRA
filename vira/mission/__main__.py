"""Run a mission standalone (no login, no kernel) with its own live dashboard:

    python -m vira.mission "Build a TallyPrime-like accounting app in Flutter"
    python -m vira.mission --mock "Any brief"          # offline, scripted fake model
    python -m vira.mission --max-agents 6 --port 8766 "Labour payment app in Flutter"

Open http://127.0.0.1:8766/ . Output lands in data/missions/<id>/project (also downloadable as zip).
"""
import argparse
import asyncio
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from loguru import logger

from vira.api.routes_mission import build_mission_router
from vira.mission.crew import MissionManager
from vira.mission.llm import MockLLM, make_ask


async def amain(a):
    over = {k: v for k, v in {"max_agents": a.max_agents, "min_agents": a.min_agents, "max_llm_calls": a.max_calls,
                              "review_rounds": a.review_rounds, "data_dir": a.data_dir}.items() if v is not None}
    factory = (lambda model: make_ask(MockLLM())) if a.mock else None
    mgr = MissionManager(a.config, ask_factory=factory, overrides=over)
    app = FastAPI(title="VIRA mission")
    page = Path(__file__).resolve().parent.parent / "web" / "static" / "mission.html"
    app.include_router(build_mission_router(None, mgr))
    app.get("/")(lambda: FileResponse(str(page), headers={"Cache-Control": "no-cache"}))
    server = uvicorn.Server(uvicorn.Config(app, host=a.host, port=a.port, log_level="warning"))
    if a.brief:
        m = await mgr.start(a.brief)
        logger.info("mission {} started", m.id)
    logger.info("Mission dashboard: http://{}:{}/", a.host, a.port)
    await server.serve()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("brief", nargs="?", default="", help="high-level task (or start it from the web page)")
    p.add_argument("--mock", action="store_true")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--min-agents", type=int)
    p.add_argument("--max-agents", type=int)
    p.add_argument("--max-calls", type=int, help="hard cap on LLM calls for the mission")
    p.add_argument("--review-rounds", type=int)
    p.add_argument("--data-dir")
    asyncio.run(amain(p.parse_args()))


if __name__ == "__main__":
    main()
