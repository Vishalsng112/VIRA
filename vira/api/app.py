"""FastAPI application with kernel integration"""
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import asyncio
import json
import uuid
from asyncio import Future, TimeoutError as AsyncTimeoutError


from vira.agent_orchestration import router
from vira.kernel import Kernel, Event, EventPriority

from fastapi import FastAPI, HTTPException, Depends, Request, Response, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse

# Let's use starlette's middleware:
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
from loguru import logger

from vira.kernel import Kernel
from vira.auth import auth, models, database

# logger = logging.getLogger(__name__)

# Global kernel instance
_kernel: Optional[Kernel] = None


def set_kernel(kernel: Kernel):
    global _kernel
    _kernel = kernel


def get_kernel() -> Kernel:
    if _kernel is None:
        raise RuntimeError("Kernel not initialized")
    return _kernel


# Pydantic models
class EventPublishRequest(BaseModel):
    type: str
    data: Any = None
    source: str = "api"
    priority: str = "NORMAL"


class ModuleLoadRequest(BaseModel):
    module_path: str


class ContextUpdateRequest(BaseModel):
    updates: Dict[str, Any]


class ConfigUpdateRequest(BaseModel):
    key: str
    value: Any



class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


# SSE stream management
class EventStreamManager:
    def __init__(self):
        self._queues: List[asyncio.Queue] = []
        self._sub_id = None

    async def connect(self):
        queue = asyncio.Queue()
        self._queues.append(queue)
        return queue

    def disconnect(self, queue: asyncio.Queue):
        if queue in self._queues:
            self._queues.remove(queue)

    async def broadcast(self, event: Event):
        message = json.dumps({
            "type": event.type,
            "data": event.data,
            "source": event.source,
            "priority": event.priority.name,
            "correlation_id": event.correlation_id,
            "timestamp": event.timestamp,
            "verified": event.verified
        })
        for queue in self._queues:
            try:
                await queue.put(f"data: {message}\n\n")
            except Exception:
                pass


stream_manager = EventStreamManager()

def create_app(kernel: Kernel) -> FastAPI:
    set_kernel(kernel)

    app = FastAPI(title="VIRA Kernel API", version="0.1.0")

    # --- Session Middleware ---
    secret_key = kernel.config_manager.get("auth.secret_key", "default-secret-change-me")
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key,
        session_cookie="vira_session",
        max_age=kernel.config_manager.get("auth.session_max_age", 86400),
        same_site="lax",
        https_only=False,
    )

    # --- Static files ---
    static_dir = Path(__file__).parent.parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # --- Database init ---
    database.init_db()

    # --- Subscribe to kernel events for SSE immediately ---
    async def event_forwarder(event: Event):
        await stream_manager.broadcast(event)

    kernel.event_bus.subscribe_all(event_forwarder)
    logger.info("✅ API event forwarder registered")

    # --- Helper for authentication ---
    def get_current_user(request: Request) -> str:
        logger.debug(f"Session contents: {request.session}")
        user = request.session.get("user")
        if not user:
            logger.warning("User not found in session")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        return user




    # --- Public endpoints (no auth) ---

    @app.get("/")
    async def root(request: Request):
        # Redirect to login or dashboard
        if request.session.get("user"):
            return RedirectResponse(url="/dashboard", status_code=302)
        if auth.admin_exists():
            return RedirectResponse(url="/login", status_code=302)
        else:
            return RedirectResponse(url="/setup", status_code=302)

    @app.get("/login")
    async def login_page(request: Request):
        if request.session.get("user"):
            return RedirectResponse(url="/dashboard", status_code=302)
        if not auth.admin_exists():
            return RedirectResponse(url="/setup", status_code=302)
        return FileResponse(str(static_dir / "login.html"))

    @app.get("/setup")
    async def setup_page(request: Request):
        if auth.admin_exists():
            return RedirectResponse(url="/login", status_code=302)
        return FileResponse(str(static_dir / "setup.html"))

    @app.get("/dashboard")
    async def dashboard_page(request: Request):
        user = request.session.get("user")
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        return FileResponse(str(static_dir / "dashboard.html"))

    @app.get("/forgot")
    async def forgot_page():
        return FileResponse(str(static_dir / "forgot.html"))

    # --- Auth API endpoints ---

    @app.post("/api/setup")
    async def setup_admin(data: models.SetupRequest):
        if auth.admin_exists():
            raise HTTPException(status_code=400, detail="Admin already exists")
        if data.password != data.confirm_password:
            raise HTTPException(status_code=400, detail="Passwords do not match")
        if len(data.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        recovery_code = auth.create_admin(data.username, data.password)
        # Return recovery code to be shown to user (they should save it)
        return {"status": "success", "message": "Admin created", "recovery_code": recovery_code}

    @app.post("/api/login")
    async def login(request: Request, data: models.LoginRequest):
        if not auth.authenticate_user(data.username, data.password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        request.session["user"] = data.username
        return {"status": "success"}

    @app.post("/api/logout")
    async def logout(request: Request):
        request.session.pop("user", None)
        return {"status": "success"}

    @app.post("/api/forgot")
    async def forgot_password(data: models.ForgotRequest):
        if data.new_password != data.confirm_password:
            raise HTTPException(status_code=400, detail="Passwords do not match")
        if len(data.new_password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        success = auth.reset_password(data.username, data.recovery_code, data.new_password)
        if not success:
            raise HTTPException(status_code=400, detail="Invalid username or recovery code")
        return {"status": "success", "message": "Password reset successfully"}

    # --- Protected API endpoints (require authentication) ---

    @app.get("/modules")
    async def list_modules(user: str = Depends(get_current_user)):
        return kernel.module_manager.list_modules()

    @app.post("/modules/load")
    async def load_module(request: ModuleLoadRequest, user: str = Depends(get_current_user)):
        # ... existing logic ...
        success = await kernel.module_manager.load_module(request.module_path)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to load module")
        return {"status": "loaded", "module": request.module_path}

    # @app.post("/events/publish")
    # async def publish_event(request: EventPublishRequest, user: str = Depends(get_current_user)):
    #     # ... existing logic ...
    #     try:
    #         priority = getattr(EventPriority, request.priority.upper(), EventPriority.NORMAL)
    #     except AttributeError:
    #         priority = EventPriority.NORMAL
    #     event = Event(type=request.type, data=request.data, source=request.source, priority=priority)
    #     event = await kernel.event_pipeline.process(event)
    #     await kernel.event_bus.publish(event)
    #     kernel.metrics_manager.increment_counter("events_published", labels={"type": request.type})
    #     return {"status": "published", "correlation_id": event.correlation_id}

    @app.post("/events/publish")
    async def publish_event(request: EventPublishRequest, user: str = Depends(get_current_user)):
        try:
            priority = getattr(EventPriority, request.priority.upper(), EventPriority.NORMAL)
        except AttributeError:
            priority = EventPriority.NORMAL

        event = Event(
            type=request.type,
            data=request.data,
            source=request.source,
            priority=priority,
        )

        # Let the dispatcher handle security, pipeline, and metrics
        try:
            count = await kernel.dispatcher.publish(event)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))

        return {
            "status": "published",
            "correlation_id": event.correlation_id,
            "subscribers": count,
        }

    @app.get("/events/stream")
    async def stream_events(request: Request, user: str = Depends(get_current_user)):
        queue = await stream_manager.connect()
        async def event_generator():
            try:
                while True:
                    data = await queue.get()
                    yield data
            except asyncio.CancelledError:
                stream_manager.disconnect(queue)
                raise
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )

    @app.get("/context")
    async def get_context(user: str = Depends(get_current_user)):
        return await kernel.context_manager.get_current_context()

    @app.post("/context/update")
    async def update_context(request: ContextUpdateRequest, user: str = Depends(get_current_user)):
        new_context = await kernel.context_manager.update_context(request.updates)
        return {"status": "updated", "context": new_context}

    @app.get("/config")
    async def get_config(user: str = Depends(get_current_user)):
        return kernel.config_manager.get_all()

    @app.post("/config/update")
    async def update_config(request: ConfigUpdateRequest, user: str = Depends(get_current_user)):
        kernel.config_manager.set(request.key, request.value)
        return {"status": "updated", "key": request.key, "value": request.value}

    @app.get("/metrics")
    async def get_metrics(user: str = Depends(get_current_user)):
        return kernel.metrics_manager.get_metrics()

    @app.get("/health")
    async def health(user: str = Depends(get_current_user)):
        health_status = await kernel.health_check()
        # Add overall health derived from sub-checks (optional)
        overall = "healthy" if kernel.is_running() else "unhealthy"
        # You could also check agent status, etc.
        return {
            "status": overall,
            **health_status
        }

    @app.post("/chat")
    async def chat_endpoint(request: ChatRequest, user: str = Depends(get_current_user)):
        kernel = get_kernel()
        conversation_id = request.conversation_id or str(uuid.uuid4())

        response_future = Future()

        async def on_response(event: Event):
            if (event.type == "agent.response" and
                event.data.get("conversation_id") == conversation_id and
                not response_future.done()):
                response_future.set_result(event.data)

        kernel.event_bus.subscribe_all(on_response)

        try:
            event = Event(
                type="user.message",
                data={"message": request.message, "conversation_id": conversation_id},
                source="api",
            )
            await kernel.dispatcher.publish(event)

            result = await asyncio.wait_for(response_future, timeout=200)
            return {
                "conversation_id": conversation_id,
                "response": result.get("response")
            }
        except AsyncTimeoutError:
            raise HTTPException(status_code=504, detail="Agent did not respond")
        finally:
            kernel.event_bus.unsubscribe_all(on_response)
    return app