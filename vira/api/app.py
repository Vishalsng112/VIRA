"""FastAPI application with kernel integration"""
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import asyncio
import json
import time
import uuid
from asyncio import Future, TimeoutError as AsyncTimeoutError


from vira.agent_orchestration import router
from vira.kernel import Kernel, Event, EventPriority
from vira.kernel import EventKind
from vira.auth import database as auth_database

from fastapi import FastAPI, HTTPException, Depends, Request, Response, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse

# Let's use starlette's middleware:
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.cors import CORSMiddleware
from pathlib import Path
from loguru import logger

from vira.kernel import Kernel
from vira.auth import auth, models, database
from vira import errors
from vira.api.deps import (
    build_auth_dependencies,
    correlation_id_of,
    install_error_handling,
)
from vira.api.streams import EventStreamManager
from vira.ratelimit import RateLimitMiddleware
from vira.agent.progress import hub as progress_hub
from vira.llm import catalog as model_catalog
from vira.llm import guidance as model_guidance
from vira.security.redaction import redact as redact_secrets
from vira.api.routes_account import build_account_router
from vira.api.routes_admin import build_admin_router
from vira.api.routes_notifications import build_notification_router
from vira.api.routes_workflows import build_workflow_router
from vira.api.routes_rag import build_rag_router
from vira.api.routes_plugins import build_plugin_router
from vira.api.routes_mcp import build_mcp_router
from vira.api.routes_organizations import build_organization_router
from vira.api.routes_storage import build_storage_router
from vira.api.routes_usage import build_usage_router
from vira.api.routes_updates import build_update_router
from vira.api.routes_approvals import build_approval_router
from vira.api.routes_generated import build_generated_router
from vira.api.routes_devices import build_device_router
from vira.api.routes_client import build_client_router
from vira.family import store as family_store

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
    kind: EventKind = EventKind.DOMAIN
    durable: bool = False


class ModuleLoadRequest(BaseModel):
    module_path: str


class ContextUpdateRequest(BaseModel):
    updates: Dict[str, Any]


class ConfigUpdateRequest(BaseModel):
    key: str
    value: Any


class ConfigReplaceRequest(BaseModel):
    config: Dict[str, Any]


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    agent_id: Optional[str] = None
    metadata: Dict[str, Any] = {}
    # Optional device context: validated against the caller's device grants.
    device_id: Optional[str] = None
    # Retry an existing run without duplicating the user's message.
    retry_run_id: Optional[str] = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class ConversationCreateRequest(BaseModel):
    title: str = "New conversation"
    incognito: bool = False


class ConversationUpdateRequest(BaseModel):
    title: Optional[str] = None
    archived: Optional[bool] = None


class MemoryFeedbackRequest(BaseModel):
    useful: bool = True
    note: Optional[str] = None
    muted: Optional[bool] = None


class MemoryCreateRequest(BaseModel):
    content: str
    agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    memory_type: str = "long_term"
    metadata: Dict[str, Any] = {}
    importance: float = 0.0
    expires_at: Optional[str] = None


class AgentStateRequest(BaseModel):
    enabled: bool


class ModelSelectRequest(BaseModel):
    model: str


class DiagnosticReportRequest(BaseModel):
    app: Optional[str] = None
    app_version: Optional[str] = None
    protocol_version: Optional[int] = None
    platform: Optional[str] = None
    device_type: Optional[str] = None
    os_version: Optional[str] = None
    generated_at: Optional[str] = None
    capture_enabled: Optional[bool] = None
    auto_sync: Optional[bool] = None
    pending_events: Optional[int] = None
    sync_state: Optional[str] = None
    last_sync_error: Optional[str] = None
    collectors: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []


stream_manager = EventStreamManager()

_SECRET_MARKERS = ("secret", "api_key", "password", "token")


def _error_text(detail: Any) -> str:
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or detail)
    return str(detail)


def _chat_http_error(status_code: int, detail: Any, *, stage: str,
                     run_id: Optional[str] = None,
                     conversation_id: Optional[str] = None,
                     user_message: Optional[str] = None,
                     recoverable: bool = True,
                     next_steps: Optional[List[str]] = None) -> HTTPException:
    """HTTPException carrying the recovery context the chat UI needs."""
    exc = HTTPException(status_code=status_code, detail=detail)
    exc.chat_context = {
        "stage": stage,
        "run_id": run_id,
        "conversation_id": conversation_id,
        "user_message": user_message,
        "recoverable": recoverable,
        "next_steps": next_steps or [],
    }
    return exc


def _redact(value):
    """Never return secrets (session key, provider API keys) from /config."""
    if isinstance(value, dict):
        return {
            k: "***" if any(m in str(k).lower() for m in _SECRET_MARKERS) else _redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def create_app(kernel: Kernel) -> FastAPI:
    set_kernel(kernel)

    app = FastAPI(title="VIRA Server API", version="0.4.0")
    install_error_handling(app)

    @app.middleware("http")
    async def request_observability(request: Request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            try:
                kernel.metrics_manager.record_error("http_500", request.url.path)
            except Exception:
                pass
            raise
        duration = time.perf_counter() - started
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        try:
            labels = {"method": request.method, "path": path, "status": str(response.status_code)}
            kernel.metrics_manager.increment_counter("http_requests_total", labels=labels)
            kernel.metrics_manager.observe_histogram("http_request_duration_seconds", duration, labels=labels)
        except Exception:
            pass
        response.headers["X-Response-Time-ms"] = f"{duration * 1000:.1f}"
        return response

    # --- Session Middleware ---
    secret_key = kernel.config_manager.get("auth.secret_key", "default-secret-change-me")
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key,
        session_cookie="vira_session",
        max_age=kernel.config_manager.get("auth.session_max_age", 86400),
        same_site="lax",
        https_only=bool(kernel.config_manager.get("auth.https_only", True)),
    )
    if not bool(kernel.config_manager.get("auth.https_only", True)):
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    rate_config = kernel.config_manager.get("rate_limits", {}) or {}
    app.add_middleware(
        RateLimitMiddleware,
        enabled=bool(rate_config.get("enabled", True)),
    )

    # --- Static files ---
    static_dir = Path(__file__).parent.parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # --- Database init ---
    database.init_db()
    interrupted = database.mark_interrupted_runs()
    if interrupted:
        logger.warning("Marked {} interrupted agent run(s) as failed and resumable", interrupted)
    family_store.ensure_schema()

    # --- Subscribe to kernel events for SSE immediately ---
    async def event_forwarder(event: Event):
        await stream_manager.broadcast(event)

    kernel.event_bus.subscribe_all(event_forwarder)
    logger.info("✅ API event forwarder registered")

    # --- Typed principals: user session, device credential, admin gate ---
    session_max_age = kernel.config_manager.get("auth.session_max_age", 86400)
    auth_deps = build_auth_dependencies(kernel)
    get_current_user = auth_deps["get_current_user"]
    require_admin = auth_deps["require_admin"]

    # --- Public endpoints (no auth) ---

    @app.get("/")
    async def root(request: Request):
        # Redirect to login or dashboard
        principal = auth.resolve_principal(request.session.get("session_id"))
        if principal:
            return RedirectResponse(url="/dashboard" if principal.is_admin else "/chat", status_code=302)
        if auth.admin_exists():
            return RedirectResponse(url="/login", status_code=302)
        else:
            return RedirectResponse(url="/setup", status_code=302)

    @app.get("/login")
    async def login_page(request: Request):
        principal = auth.resolve_principal(request.session.get("session_id"))
        if principal:
            return RedirectResponse(url="/dashboard" if principal.is_admin else "/chat", status_code=302)
        if not auth.admin_exists():
            return RedirectResponse(url="/setup", status_code=302)
        return FileResponse(str(static_dir / "login.html"))

    @app.get("/setup")
    async def setup_page(request: Request):
        if auth.admin_exists():
            return RedirectResponse(url="/login", status_code=302)
        return FileResponse(str(static_dir / "style.html"))

    @app.get("/dashboard")
    async def dashboard_page(request: Request):
        principal = auth.resolve_principal(request.session.get("session_id"))
        if not principal:
            return RedirectResponse(url="/login", status_code=302)
        if not principal.is_admin:
            return RedirectResponse(url="/chat", status_code=302)
        return FileResponse(
            str(static_dir / "dashboard.html"),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    @app.get("/chat")
    async def chat_page(request: Request):
        if not auth.resolve_principal(request.session.get("session_id")):
            return RedirectResponse(url="/login", status_code=302)
        return FileResponse(str(static_dir / "chat.html"), headers={"Cache-Control": "no-cache"})

    @app.get("/forgot")
    async def forgot_page():
        return FileResponse(str(static_dir / "forgot.html"))

    # --- Auth API endpoints ---

    @app.post("/api/v1/auth/setup")
    async def setup_admin(data: models.SetupRequest):
        if auth.admin_exists():
            raise HTTPException(status_code=400, detail="Admin already exists")
        if data.password != data.confirm_password:
            raise HTTPException(status_code=400, detail="Passwords do not match")
        if len(data.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        try:
            recovery_code = auth.create_admin(data.username, data.password)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        database.record_auth_audit("setup", "user.create_admin", True)
        if kernel.local_device:
            kernel.local_device.sync_access()  # the new admin owns the server device
        # Return recovery code to be shown to user (they should save it)
        return {"status": "success", "message": "Admin created", "recovery_code": recovery_code}

    @app.post("/api/v1/auth/login")
    async def login(request: Request, data: models.LoginRequest):
        user = auth.authenticate_user_record(data.username, data.password)
        if not user:
            database.record_auth_audit("login", "session.create", False, resource=data.username)
            raise HTTPException(status_code=401, detail="Invalid credentials")
        session_id = auth.create_authenticated_session(user, session_max_age)
        request.session.clear()
        request.session["session_id"] = session_id
        database.record_auth_audit("login", "session.create", True, user_id=int(user["id"]), session_id=session_id)
        return {
            "status": "success",
            "principal": {
                "user_id": int(user["id"]),
                "username": user["username"],
                "roles": [user["role"]],
                "session_id": session_id,
            },
        }

    @app.post("/api/v1/auth/logout")
    async def logout(request: Request):
        session_id = request.session.get("session_id")
        principal = auth.resolve_principal(session_id)
        if session_id:
            auth.revoke_session(session_id, principal.user_id if principal else None)
        request.session.clear()
        return {"status": "success"}

    @app.post("/api/v1/auth/password/reset")
    async def forgot_password(data: models.ForgotRequest):
        if data.new_password != data.confirm_password:
            raise HTTPException(status_code=400, detail="Passwords do not match")
        if len(data.new_password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        success = auth.reset_password(data.username, data.recovery_code, data.new_password)
        if not success:
            raise HTTPException(status_code=400, detail="Invalid username or recovery code")
        return {"status": "success", "message": "Password reset successfully"}

    @app.get("/api/v1/auth/me")
    async def current_principal(principal: auth.Principal = Depends(get_current_user)):
        return {
            "user_id": principal.user_id,
            "user_public_id": principal.public_id,
            "username": principal.username,
            "roles": list(principal.roles),
            "session_id": principal.session_id,
        }

    @app.post("/api/v1/diagnostics")
    async def submit_client_diagnostics(
        report: DiagnosticReportRequest,
        principal: auth.Principal = Depends(get_current_user),
    ):
        """Store an opt-in, already-redacted client diagnostic report."""
        payload = redact_secrets(report.model_dump())
        database.record_auth_audit(
            "client_diagnostic",
            "diagnostics.submit",
            True,
            user_id=principal.user_id,
            resource=payload.get("platform"),
            details=json.dumps(payload, default=str)[:8000],
            target=str(payload.get("app_version") or "")[:100],
        )
        return {"status": "recorded"}

    app.add_api_route("/api/v1/auth/bootstrap", setup_admin, methods=["POST"])

    @app.post("/api/v1/auth/password/change")
    async def change_password(data: PasswordChangeRequest, request: Request,
                              principal: auth.Principal = Depends(get_current_user)):
        if len(data.new_password) < 8:
            raise errors.ValidationFailed("Password must be at least 8 characters")
        if not auth.change_password(principal.user_id, data.current_password, data.new_password):
            raise errors.Forbidden("Current password is incorrect", code="invalid_credentials")
        request.session.clear()  # every session, including this one, was revoked
        return {"status": "success"}

    @app.post("/api/v1/auth/sessions/revoke-all")
    async def revoke_all_sessions(request: Request,
                                  principal: auth.Principal = Depends(get_current_user)):
        database.revoke_user_sessions(principal.user_id)
        database.record_auth_audit("logout", "session.revoke_all", True, user_id=principal.user_id)
        request.session.clear()
        return {"status": "success"}

    # Compatibility aliases for the current local UI.
    app.add_api_route("/api/setup", setup_admin, methods=["POST"])
    app.add_api_route("/api/login", login, methods=["POST"])
    app.add_api_route("/api/logout", logout, methods=["POST"])
    app.add_api_route("/api/forgot", forgot_password, methods=["POST"])

    # --- Protected API endpoints (require authentication) ---

    @app.get("/modules")
    async def list_modules(user: auth.Principal = Depends(require_admin)):
        return kernel.module_manager.list_modules()

    @app.post("/modules/load")
    async def load_module(request: ModuleLoadRequest, user: auth.Principal = Depends(require_admin)):
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
    async def publish_event(request: EventPublishRequest, http_request: Request,
                            user: auth.Principal = Depends(require_admin)):
        """Legacy administrator tool.

        ``source`` is only a descriptive label (it is not authentication).  The
        human actor comes from the authenticated session; the event carries no
        device identity, so it is visible on streams to administrators and the
        acting user only.  Endpoint devices must use /api/v1/devices/{id}/events:batch.
        """
        try:
            priority = getattr(EventPriority, request.priority.upper(), EventPriority.NORMAL)
        except AttributeError:
            priority = EventPriority.NORMAL

        event = Event(
            type=request.type,
            data=request.data,
            source=f"api:{request.source}"[:64],
            priority=priority,
            kind=request.kind,
            durable=request.durable,
            actor_user_id=user.user_id,
            source_component="admin-api",
            correlation_id=correlation_id_of(http_request),
        )
        try:
            count = await kernel.dispatcher.publish(event)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        database.record_auth_audit(
            "admin", "event.publish", True, user_id=user.user_id, resource=f"event:{request.type}",
            correlation_id=event.correlation_id,
        )
        return {
            "status": "published",
            "correlation_id": event.correlation_id,
            "subscribers": count,
        }

    async def _stream(request: Request, user: auth.Principal):
        sub = stream_manager.connect(user.user_id, user.is_admin, user.session_id)

        async def event_generator():
            try:
                idle = 0
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        data = await asyncio.wait_for(sub.queue.get(), timeout=15)
                        idle = 0
                        yield data
                    except asyncio.TimeoutError:
                        # Keep-alive; also re-validate the session so a revoked or
                        # disabled user's stream ends promptly.
                        if not auth.resolve_principal(user.session_id):
                            break
                        yield ": ping\n\n"
            except asyncio.CancelledError:
                raise
            finally:
                stream_manager.disconnect(sub)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    @app.get("/events/stream")
    async def stream_events(request: Request, user: auth.Principal = Depends(get_current_user)):
        return await _stream(request, user)

    app.add_api_route("/api/v1/events/stream", stream_events, methods=["GET"])

    @app.get("/context")
    async def get_context(user: auth.Principal = Depends(require_admin)):
        return await kernel.context_manager.get_current_context()

    @app.post("/context/update")
    async def update_context(request: ContextUpdateRequest, user: auth.Principal = Depends(require_admin)):
        new_context = await kernel.context_manager.update_context(request.updates)
        return {"status": "updated", "context": new_context}

    @app.get("/config")
    async def get_config(user: auth.Principal = Depends(require_admin)):
        return _redact(kernel.config_manager.get_all())

    @app.post("/config/update")
    async def update_config(request: ConfigUpdateRequest, user: auth.Principal = Depends(require_admin)):
        kernel.config_manager.set(request.key, request.value)
        return {"status": "updated", "key": request.key, "value": request.value}

    @app.put("/config")
    async def replace_config(request: ConfigReplaceRequest, user: auth.Principal = Depends(require_admin)):
        current = kernel.config_manager.get_all()
        updated = request.config

        def preserve_redacted_values(value: Any, existing: Any) -> Any:
            if isinstance(value, dict) and isinstance(existing, dict):
                return {
                    key: preserve_redacted_values(item, existing.get(key))
                    for key, item in value.items()
                }
            if value == "***" and existing is not None:
                return existing
            return value

        updated = preserve_redacted_values(updated, current)
        kernel.config_manager.save(updated)
        await kernel.reload()
        return {"status": "reloaded", "config": _redact(kernel.config_manager.get_all())}

    @app.get("/metrics")
    async def get_metrics(user: auth.Principal = Depends(require_admin)):
        return kernel.metrics_manager.get_metrics()

    @app.get("/livez")
    async def livez():
        """Unauthenticated liveness probe for containers and load balancers."""
        return {"status": "ok", "service": "vira-server"}

    @app.get("/health")
    async def health(user: auth.Principal = Depends(require_admin)):
        health_status = await kernel.health_check()
        # Add overall health derived from sub-checks (optional)
        overall = "healthy" if kernel.is_running() else "unhealthy"
        # You could also check agent status, etc.
        return {
            "status": overall,
            **health_status
        }

    @app.get("/ops/sensors")
    async def sensor_status(user: auth.Principal = Depends(require_admin)):
        return {"sensors": [sensor.health() for sensor in kernel._sensors]}

    @app.get("/ops/events/lag")
    async def event_lag(user: auth.Principal = Depends(require_admin)):
        pending = kernel.event_bus.pending_events()
        capacity = kernel.event_bus._max_queue_size
        return {
            "pending_events": pending,
            "capacity": capacity,
            "utilization": pending / capacity if capacity else 0.0,
            "outbox": auth_database.outbox_counts(),
        }

    @app.get("/ops/events/failed")
    async def failed_events(user: auth.Principal = Depends(require_admin)):
        counts = auth_database.outbox_counts()
        return {
            "dead_letter": counts.get("dead_letter", 0),
            "processing": counts.get("processing", 0),
            "pending": counts.get("pending", 0),
        }

    @app.get("/orchestration")
    async def orchestration_status(user: auth.Principal = Depends(require_admin)):
        """Return the current agent orchestration runtime state."""
        orchestrator = getattr(kernel, "agent_orchestrator", None)
        if orchestrator is None:
            return {
                "available": False,
                "running": False,
                "agents": [],
                "router": {"running": False, "subscribed": False},
                "scheduler": {
                    "max_concurrent": 0,
                    "running_tasks": 0,
                    "pending_tasks": 0,
                },
                "runtime": {
                    "memory_manager": "not_available",
                    "llm_manager": "not_available",
                },
                "tools": {"total": 0, "names": [], "metadata": [], "mcp_connections": 0},
            }

        registry = getattr(orchestrator, "registry", None)
        agents = []
        if registry is not None:
            for metadata in await registry.list_agents():
                capabilities = [
                    capability.dict() if hasattr(capability, "dict") else capability
                    for capability in (metadata.capabilities or [])
                ]
                agents.append({
                    "id": metadata.agent_id,
                    "name": metadata.name,
                    "version": metadata.version,
                    "description": metadata.description,
                    "state": metadata.state.value,
                    "enabled": metadata.enabled,
                    "capabilities": capabilities,
                    "subscribed_events": metadata.subscribed_events,
                    "interval_seconds": metadata.interval_seconds,
                    "created_at": metadata.created_at,
                    "updated_at": metadata.updated_at,
                })

        scheduler = getattr(orchestrator, "runtime_scheduler", None)
        running_tasks = getattr(scheduler, "_running_tasks", {}) if scheduler else {}
        router_instance = getattr(orchestrator, "router", None)
        tool_registry = getattr(orchestrator, "tool_registry", None)
        tool_names = tool_registry.list() if tool_registry else []
        tool_metadata = tool_registry.metadata() if tool_registry else []
        runtime = getattr(orchestrator, "runtime", None)

        return {
            "available": True,
            "running": bool(getattr(orchestrator, "_running", False)),
            "agents": agents,
            "router": {
                "running": bool(getattr(router_instance, "_running", False)),
                "subscribed": bool(getattr(router_instance, "_subscription_id", None)),
            },
            "scheduler": {
                "max_concurrent": getattr(scheduler, "_max_concurrent", 0) if scheduler else 0,
                "running_tasks": len(running_tasks),
                "pending_tasks": 0,
            },
            "runtime": {
                "memory_manager": "initialized" if runtime and getattr(runtime, "_memory", None) else "not_available",
                "llm_manager": "initialized" if runtime and getattr(runtime, "_llm", None) else "not_available",
            },
            "tools": {
                "total": len(tool_names),
                "names": tool_names,
                "metadata": tool_metadata,
                "mcp_connections": len(getattr(orchestrator, "_mcp_connections", [])),
            },
        }

    # --- Model discovery and switching (first-run recovery) -------------
    def _ollama_runtime():
        config = kernel.config_manager.get_all()
        base_url = model_catalog.configured_ollama_url(config)
        default_model = model_catalog.configured_model(config)
        orchestrator = getattr(kernel, "agent_orchestrator", None)
        runtime = getattr(orchestrator, "runtime", None)
        llm = getattr(runtime, "_llm", None) if runtime else None
        current = default_model
        if llm is not None:
            for provider in getattr(llm, "_providers", {}).values():
                if provider.__class__.__name__ == "OllamaProvider":
                    current = getattr(provider, "model", None) or current
                    break
        return config, base_url, default_model, current, llm

    @app.get("/api/v1/models")
    async def list_models(user: auth.Principal = Depends(get_current_user)):
        """Installed Ollama models plus the configured and active model."""
        config, base_url, default_model, current_model, _llm = _ollama_runtime()
        reachable = True
        error = None
        try:
            installed = await asyncio.to_thread(model_catalog.list_ollama_models, base_url, 3.0)
        except Exception as exc:  # noqa: BLE001 - surface a helpful state, not a 500
            installed = []
            reachable = False
            error = str(exc)
        names = {item["name"] for item in installed}
        if default_model and default_model not in names:
            installed.append({
                "name": default_model,
                "size": None,
                "parameter_size": None,
                "quantization": None,
                "family": None,
                "modified_at": None,
                "installed": False,
            })
            names.add(default_model)
        for item in installed:
            item.setdefault("installed", reachable)
            item["current"] = item["name"] == current_model
            item["configured"] = item["name"] == default_model
        ram = model_guidance.hardware_ram_gb()
        return {
            "provider": "ollama",
            "ollama_url": base_url,
            "reachable": reachable,
            "error": error,
            "default_model": default_model,
            "current_model": current_model,
            "num_ctx": model_catalog.configured_context(config),
            "models": installed,
            "can_select": bool(getattr(user, "is_admin", False)),
            "guidance": model_guidance.recommend(ram),
            "cloud_fallback": model_guidance.cloud_fallback(),
        }

    @app.post("/api/v1/models/select")
    async def select_model(request: ModelSelectRequest,
                            user: auth.Principal = Depends(require_admin)):
        """Switch the active Ollama model without restarting the server."""
        chosen = (request.model or "").strip()
        if not chosen:
            raise HTTPException(status_code=400, detail="model is required")
        config, base_url, default_model, current_model, llm = _ollama_runtime()
        try:
            installed = await asyncio.to_thread(model_catalog.list_ollama_models, base_url, 3.0)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "model_unreachable",
                    "message": f"Ollama is not reachable at {base_url}: {exc}",
                    "next_steps": [
                        "Start Ollama (`ollama serve`) or fix VIRA_OLLAMA_URL.",
                        "Run `python -m vira doctor` to re-check the endpoint.",
                    ],
                },
            ) from exc
        names = {item["name"] for item in installed}
        if chosen not in names:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "model_not_installed",
                    "message": f"'{chosen}' is not installed in Ollama.",
                    "available": sorted(names),
                    "next_steps": [f"Run `ollama pull {chosen}`, then retry."],
                },
            )

        llm_config = config.setdefault("llm", {})
        llm_config["default_model"] = chosen
        for entry in llm_config.get("models", []) or []:
            if entry.get("provider") == "ollama":
                entry["model"] = chosen
        kernel.config_manager.save(config)

        if llm is not None:
            for provider_name, provider in getattr(llm, "_providers", {}).items():
                if provider.__class__.__name__ == "OllamaProvider":
                    provider.model = chosen
                    routing = llm._routing_config.setdefault(chosen, [])
                    if provider_name not in routing:
                        routing.append(provider_name)
        registry = getattr(getattr(kernel, "agent_orchestrator", None), "registry", None)
        for agent in getattr(registry, "_agent_instances", {}).values():
            if getattr(agent, "model", None) is not None:
                agent.model = chosen
        logger.info("Active chat model switched from {} to {}", current_model, chosen)
        return {
            "status": "updated",
            "model": chosen,
            "previous_model": current_model,
            "default_model": default_model,
        }

    @app.get("/agents")
    async def list_agents(user: auth.Principal = Depends(require_admin)):
        orchestrator = getattr(kernel, "agent_orchestrator", None)
        loaded = []
        registry = getattr(orchestrator, "registry", None) if orchestrator else None
        if registry:
            loaded = [
                metadata.dict() if hasattr(metadata, "dict") else metadata
                for metadata in await registry.list_agents()
            ]
        persisted = auth_database.list_agent_definitions()
        return {"agents": persisted, "loaded": loaded}

    @app.patch("/agents/{agent_id}")
    async def set_agent_state(
        agent_id: str,
        request: AgentStateRequest,
        user: auth.Principal = Depends(require_admin),
    ):
        orchestrator = getattr(kernel, "agent_orchestrator", None)
        registry = getattr(orchestrator, "registry", None) if orchestrator else None
        if not registry or not await registry.set_enabled(agent_id, request.enabled):
            raise HTTPException(status_code=404, detail="Agent not found")
        if not auth_database.set_agent_definition_enabled(agent_id, request.enabled):
            raise HTTPException(status_code=404, detail="Agent definition not found")
        return {"agent_id": agent_id, "enabled": request.enabled}

    @app.delete("/agents/{agent_id}")
    async def unregister_agent(agent_id: str, user: auth.Principal = Depends(require_admin)):
        orchestrator = getattr(kernel, "agent_orchestrator", None)
        registry = getattr(orchestrator, "registry", None) if orchestrator else None
        if not registry or not await registry.unregister(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        auth_database.delete_agent_definition(agent_id)
        return {"status": "unregistered", "agent_id": agent_id}

    @app.get("/tools/calls")
    async def list_tool_calls(user: auth.Principal = Depends(require_admin)):
        return {"tool_calls": auth_database.list_tool_calls()}

    @app.post("/conversations")
    async def create_conversation(
        request: ConversationCreateRequest,
        user: auth.Principal = Depends(get_current_user),
    ):
        conversation_id = auth_database.create_conversation(
            user.user_id, request.title, incognito=request.incognito
        )
        return auth_database.get_conversation(conversation_id, user.user_id)

    @app.get("/conversations")
    async def list_conversations(
        limit: int = 50,
        offset: int = 0,
        user: auth.Principal = Depends(get_current_user),
    ):
        return {"conversations": auth_database.list_conversations(user.user_id, limit, offset)}

    @app.get("/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str, user: auth.Principal = Depends(get_current_user)):
        conversation = auth_database.get_conversation(conversation_id, user.user_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conversation

    @app.patch("/conversations/{conversation_id}")
    async def update_conversation(
        conversation_id: str,
        request: ConversationUpdateRequest,
        user: auth.Principal = Depends(get_current_user),
    ):
        if not auth_database.update_conversation(
            conversation_id, user.user_id, request.title, request.archived
        ):
            raise HTTPException(status_code=404, detail="Conversation not found")
        return auth_database.get_conversation(conversation_id, user.user_id)

    @app.delete("/conversations/{conversation_id}")
    async def delete_conversation(conversation_id: str, user: auth.Principal = Depends(get_current_user)):
        if not auth_database.delete_conversation(conversation_id, user.user_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"status": "deleted", "conversation_id": conversation_id}

    @app.get("/conversations/{conversation_id}/messages")
    async def list_messages(
        conversation_id: str,
        limit: int = 50,
        offset: int = 0,
        user: auth.Principal = Depends(get_current_user),
    ):
        if not auth_database.get_conversation(conversation_id, user.user_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"messages": auth_database.list_messages(conversation_id, user.user_id, limit, offset)}

    @app.get("/runs")
    async def list_runs(status: Optional[str] = None, limit: int = 50,
                        user: auth.Principal = Depends(get_current_user)):
        return {"runs": auth_database.list_runs(user.user_id, status, limit)}

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str, user: auth.Principal = Depends(get_current_user)):
        run = auth_database.get_run(run_id, user.user_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @app.post("/runs/{run_id}/resume")
    async def resume_run(run_id: str, http_request: Request,
                         user: auth.Principal = Depends(get_current_user)):
        """Resume a failed/interrupted run with its original user message."""
        run = auth_database.get_run(run_id, user.user_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.get("status") not in ("failed", "queued"):
            raise HTTPException(
                status_code=409,
                detail=f"Only failed or queued runs can be resumed (current: {run.get('status')})",
            )
        if not run.get("input_message_id"):
            raise HTTPException(status_code=409, detail="Run has no original message")
        request = ChatRequest(
            message="",
            conversation_id=run["conversation_id"],
            retry_run_id=run_id,
        )
        result = await _submit_chat(
            request, http_request, user,
            conversation_id=run["conversation_id"],
            idempotency_key_override=str(uuid.uuid4()),
        )
        return {**result, "resumed_from": run_id}

    @app.get("/runs/{run_id}/events")
    async def get_run_events(run_id: str, after: int = 0, limit: int = 500,
                             user: auth.Principal = Depends(get_current_user)):
        if not auth_database.get_run(run_id, user.user_id):
            raise HTTPException(status_code=404, detail="Run not found")
        from vira.agent_runtime.run_store import list_events
        return {"events": list_events(run_id, after, limit)}

    @app.get("/runs/{run_id}/timeline")
    async def get_run_timeline(run_id: str, user: auth.Principal = Depends(get_current_user)):
        run = auth_database.get_run(run_id, user.user_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        from vira.agent_runtime.run_store import timeline
        return {
            "run": {
                "id": run.get("id"),
                "status": run.get("status"),
                "error": run.get("error"),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
            },
            "timeline": timeline(run_id),
        }

    @app.post("/memories")
    async def create_memory(
        request: MemoryCreateRequest,
        user: auth.Principal = Depends(get_current_user),
    ):
        if request.conversation_id:
            conversation = auth_database.get_conversation(request.conversation_id, user.user_id)
            if conversation and conversation.get("incognito"):
                raise HTTPException(status_code=400, detail="Memories cannot be stored for incognito chats")
        memory_id = auth_database.store_memory(
            user_id=user.user_id,
            content=request.content,
            agent_id=request.agent_id,
            conversation_id=request.conversation_id,
            memory_type=request.memory_type,
            metadata=request.metadata,
            importance=request.importance,
            expires_at=request.expires_at,
        )
        return {"id": memory_id, "status": "stored"}

    @app.get("/memories")
    async def search_memories(
        query: str = "",
        limit: int = 10,
        agent_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        memory_type: Optional[str] = None,
        user: auth.Principal = Depends(get_current_user),
    ):
        return {
            "memories": auth_database.search_memories(
                user.user_id, query, limit, agent_id, conversation_id, memory_type
            )
        }

    @app.post("/memories/{memory_id}/feedback")
    async def memory_feedback(memory_id: str, request: MemoryFeedbackRequest,
                              user: auth.Principal = Depends(get_current_user)):
        if request.muted is not None:
            updated = auth_database.set_memory_muted(
                memory_id, user.user_id, request.muted)
        else:
            updated = auth_database.record_memory_feedback(
                memory_id, user.user_id, request.useful, request.note)
        if not updated:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {
            "status": "updated",
            "memory_id": memory_id,
            "muted": request.muted,
            "useful": request.useful if request.muted is None else None,
        }

    @app.delete("/memories/{memory_id}")
    async def delete_memory(memory_id: str, user: auth.Principal = Depends(get_current_user)):
        if not auth_database.delete_memory(memory_id, user.user_id):
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"status": "deleted", "memory_id": memory_id}

    @app.get("/security")
    async def security_status(user: auth.Principal = Depends(require_admin)):
        """Return safe, read-only security and trust information for the dashboard."""
        security_manager = getattr(kernel, "security_manager", None)
        dispatcher = getattr(kernel, "dispatcher", None)
        config_manager = getattr(kernel, "config_manager", None)
        orchestrator = getattr(kernel, "agent_orchestrator", None)
        tool_registry = getattr(orchestrator, "tool_registry", None) if orchestrator else None

        config = config_manager.get_all() if config_manager else {}
        auth_config = config.get("auth", {}) if isinstance(config, dict) else {}
        security_config = config.get("security", {}) if isinstance(config, dict) else {}
        session_max_age = auth_config.get("session_max_age", 86400)

        tool_policies = []
        if tool_registry:
            for name, tool in getattr(tool_registry, "_tools", {}).items():
                permissions = getattr(tool, "permissions", None)
                tool_policies.append({
                    "name": name,
                    "actions": list(getattr(permissions, "actions", []) or []),
                })

        return {
            "posture": {
                "authentication": "bcrypt password verification",
                "session": "signed cookie session",
                "authorization": "central permission manager",
                "event_policy": "events are marked verified/unverified and still published",
                "dashboard_access": "authenticated users only",
            },
            "authentication": {
                "admin_configured": bool(auth.admin_exists()),
                "password_hashing": "bcrypt",
                "recovery_codes": "bcrypt-hashed and never displayed",
                "session_cookie": "vira_session",
                "session_max_age_seconds": session_max_age,
                "https_only": bool(kernel.config_manager.get("auth.https_only", True)),
                "same_site": "lax",
            },
            "authorization": {
                "granted_permissions": sorted(security_manager.list_permissions()) if security_manager else [],
                "default_permissions": security_config.get("default_permissions", []),
                "deny_rules_configured": len(getattr(security_manager, "_deny_rules", set())) if security_manager else 0,
            },
            "event_dispatch": {
                "security_enabled": bool(dispatcher and getattr(dispatcher, "_security", None)),
                "pipeline_enabled": bool(dispatcher and getattr(dispatcher, "_pipeline", None)),
                "unauthorized_event_behavior": "mark verified=false, record security_denied metric, then publish",
            },
            "agent_runtime": {
                "llm_calls_require_permission": True,
                "tool_calls_require_permission": True,
                "memory_operations_require_permission": True,
            },
            "tools": {
                "registered": tool_policies,
                "mcp_connections": len(getattr(orchestrator, "_mcp_connections", [])) if orchestrator else 0,
            },
            "visibility_limits": [
                "Persistent authentication decisions are recorded in the auth_audit table.",
                "Session revocation is currently performed by logout and password reset.",
                "HTTPS is enforced for authentication cookies; terminate TLS at the configured reverse proxy.",
            ],
        }

    async def _submit_chat(
        request: ChatRequest,
        http_request: Request,
        user: auth.Principal,
        conversation_id: Optional[str] = None,
        progress_queue: Optional[asyncio.Queue] = None,
        idempotency_key_override: Optional[str] = None,
    ):
        kernel = get_kernel()
        orchestrator = getattr(kernel, "agent_orchestrator", None)
        registry = getattr(orchestrator, "registry", None) if orchestrator else None
        if not registry or not await registry.find_by_event("user.message"):
            raise _chat_http_error(
                503,
                "No chat agent is available. Enable the Chatbot agent and restart VIRA.",
                stage="agent",
                user_message=request.message,
                next_steps=[
                    "Run `python -m vira doctor` and fix the Chatbot check.",
                    "Set agents[].enabled: true for the Chatbot in config.yaml.",
                    "Restart VIRA after changing config.yaml.",
                ],
            )
        correlation_id = correlation_id_of(http_request)
        idempotency_key = idempotency_key_override or http_request.headers.get("Idempotency-Key")
        if not idempotency_key and not request.retry_run_id:
            raise _chat_http_error(
                400, "Idempotency-Key header is required", stage="request",
                user_message=request.message, recoverable=False,
            )
        # Optional device context: accepted only for a device the caller may use.
        device_id = None
        if request.device_id:
            device_id = kernel.device_service.validate_user_device(user, request.device_id)
        conversation_id = conversation_id or request.conversation_id
        if conversation_id is None:
            conversation_id = auth_database.create_conversation(user.user_id)
        conversation = auth_database.get_conversation(conversation_id, user.user_id)
        if not conversation:
            raise _chat_http_error(
                404, "Conversation not found", stage="request",
                conversation_id=conversation_id, user_message=request.message,
                recoverable=False,
            )

        retry_run = None
        if request.retry_run_id:
            retry_run = auth_database.get_run(request.retry_run_id, user.user_id)
            if not retry_run or retry_run.get("conversation_id") != conversation_id:
                raise _chat_http_error(
                    404, "Run not found in this conversation", stage="request",
                    conversation_id=conversation_id, user_message=request.message,
                    recoverable=False,
                )
            original = auth_database.get_message(retry_run["input_message_id"], user.user_id)
            if not original:
                raise _chat_http_error(
                    404, "The original message for this run no longer exists",
                    stage="request", conversation_id=conversation_id,
                    run_id=request.retry_run_id, user_message=request.message,
                    recoverable=False,
                )
            user_message = original
            message_text = str(original["content"])
            idempotency_key = None
        else:
            existing = auth_database.get_message_by_idempotency(user.user_id, idempotency_key)
            if existing:
                return {
                    "conversation_id": existing["conversation_id"],
                    "message_id": existing["id"],
                    "run_id": existing["run_id"],
                    "status": "queued",
                    "correlation_id": existing["correlation_id"],
                }
            message_text = request.message
            user_message = auth_database.append_message(
                conversation_id,
                user.user_id,
                "user",
                message_text,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                metadata=request.metadata,
                created_by_device_id=device_id,
            )
        history_rows = auth_database.list_messages(conversation_id, user.user_id, limit=20)
        history = [{"role": row["role"], "content": row["content"]} for row in history_rows]
        run_id = auth_database.create_run(
            conversation_id, user.user_id, user_message["id"],
            request.agent_id or (retry_run.get("agent_id") if retry_run else None),
            correlation_id,
        )

        response_future = Future()
        progress_hub.begin(run_id, progress_queue)
        trace: List[Dict[str, Any]] = []

        async def on_response(event: Event):
            data = event.data if isinstance(event.data, dict) else {}
            if (event.type == "agent.response" and
                data.get("conversation_id") == conversation_id and
                data.get("run_id") in (None, run_id) and
                not response_future.done()):
                response_future.set_result(data)

        kernel.event_bus.subscribe_all(on_response)

        try:
            # A user action: identity comes from the authenticated session, and the
            # optional device only after the access check above.  The event has no
            # device_id so it is streamed to this user alone.
            event = Event(
                type="user.message",
                data={
                    "message": message_text,
                    "conversation_id": conversation_id,
                    "history": history,
                    "run_id": run_id,
                    "user_id": user.user_id,
                    "device_id": device_id,
                },
                source="api",
                correlation_id=correlation_id,
                actor_user_id=user.user_id,
                source_component="chat-api",
            )
            await kernel.dispatcher.publish(event)

            result = await asyncio.wait_for(response_future, timeout=200)
            trace = progress_hub.end(run_id)
            assistant_message = auth_database.append_message(
                conversation_id,
                user.user_id,
                "assistant",
                result.get("response", ""),
                correlation_id=correlation_id,
                run_id=run_id,
                metadata={"trace": trace} if trace else None,
                created_by_device_id=None,
            )
            auth_database.update_run(run_id, "succeeded", result_message_id=assistant_message["id"])
            return {
                "conversation_id": conversation_id,
                "message_id": user_message["id"],
                "run_id": run_id,
                "response": result.get("response"),
                "status": "succeeded",
                "correlation_id": correlation_id,
            }
        except AsyncTimeoutError:
            auth_database.update_run(run_id, "failed", error="Agent did not respond")
            raise _chat_http_error(
                504,
                "The model did not answer in time. The local model may still be loading.",
                stage="model_timeout",
                run_id=run_id,
                conversation_id=conversation_id,
                user_message=message_text,
                next_steps=[
                    "Retry after the model has finished loading.",
                    "Run `python -m vira doctor` to check the model and its context size.",
                    "Switch to a smaller local model or a cloud provider if this repeats.",
                ],
            )
        except HTTPException:
            raise
        except Exception as exc:
            auth_database.update_run(run_id, "failed", error=str(exc))
            logger.exception("chat run failed")
            raise _chat_http_error(
                500,
                f"The agent failed: {type(exc).__name__}. Your message was saved.",
                stage="model",
                run_id=run_id,
                conversation_id=conversation_id,
                user_message=message_text,
                next_steps=[
                    "Retry the message; the conversation and run are preserved.",
                    "Run `python -m vira doctor` to check Ollama, the model and the database.",
                    "Switch models from the recovery panel, or use a cloud provider.",
                ],
            )
        finally:
            progress_hub.end(run_id)  # no-op if already collected
            kernel.event_bus.unsubscribe_all(on_response)

    @app.post("/chat")
    async def chat_endpoint(request: ChatRequest, http_request: Request,
                            user: auth.Principal = Depends(get_current_user)):
        return await _submit_chat(request, http_request, user)

    _stream_tasks: set = set()

    @app.post("/chat/stream")
    async def chat_stream_endpoint(request: ChatRequest, http_request: Request,
                                   user: auth.Principal = Depends(get_current_user)):
        """Same as /chat, but streams the agent's activity as NDJSON lines.

        Lines: {"type": "status|thought|tool_start|tool_end|check", ...} while the
        agent works, then one {"type": "done", ...result} or {"type": "error", ...}.
        """
        queue: asyncio.Queue = asyncio.Queue()

        async def runner():
            try:
                result = await _submit_chat(request, http_request, user, progress_queue=queue)
                await queue.put({"type": "done", **result})
            except HTTPException as exc:
                payload = {
                    "type": "error",
                    "status": exc.status_code,
                    "detail": _error_text(exc.detail),
                    "code": (exc.detail.get("code") if isinstance(exc.detail, dict) else None),
                    **getattr(exc, "chat_context", {}),
                }
                if isinstance(exc.detail, dict):
                    payload["available"] = exc.detail.get("available")
                await queue.put(payload)
            except Exception as exc:
                logger.exception("chat stream failed")
                await queue.put({
                    "type": "error",
                    "status": 500,
                    "detail": str(exc) or "Chat failed",
                    "stage": "unknown",
                    "recoverable": True,
                    "user_message": request.message,
                    "next_steps": ["Retry the message.", "Run `python -m vira doctor`."],
                })
            finally:
                await queue.put(None)

        # Keep a reference and let the run finish (and be saved) even if the tab closes.
        task = asyncio.create_task(runner())
        _stream_tasks.add(task)
        task.add_done_callback(_stream_tasks.discard)

        async def lines():
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield json.dumps(item, default=str) + "\n"

        return StreamingResponse(
            lines(), media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/v1/conversations/{conversation_id}/messages")
    async def submit_message(conversation_id: str, request: ChatRequest, http_request: Request,
                             user: auth.Principal = Depends(get_current_user)):
        return await _submit_chat(request, http_request, user, conversation_id=conversation_id)

    # --- Versioned (/api/v1) aliases of the legacy unversioned user routes ---
    # New clients must use these; the unversioned paths remain as legacy adapters.
    app.add_api_route("/api/v1/conversations", create_conversation, methods=["POST"])
    app.add_api_route("/api/v1/conversations", list_conversations, methods=["GET"])
    app.add_api_route("/api/v1/conversations/{conversation_id}", get_conversation, methods=["GET"])
    app.add_api_route("/api/v1/conversations/{conversation_id}", update_conversation, methods=["PATCH"])
    app.add_api_route("/api/v1/conversations/{conversation_id}", delete_conversation, methods=["DELETE"])
    app.add_api_route("/api/v1/conversations/{conversation_id}/messages", list_messages, methods=["GET"])
    app.add_api_route("/api/v1/runs", list_runs, methods=["GET"])
    app.add_api_route("/api/v1/runs/{run_id}", get_run, methods=["GET"])
    app.add_api_route("/api/v1/runs/{run_id}/events", get_run_events, methods=["GET"])
    app.add_api_route("/api/v1/runs/{run_id}/timeline", get_run_timeline, methods=["GET"])
    app.add_api_route("/api/v1/runs/{run_id}/resume", resume_run, methods=["POST"])
    app.add_api_route("/api/v1/memories", create_memory, methods=["POST"])
    app.add_api_route("/api/v1/memories", search_memories, methods=["GET"])
    app.add_api_route("/api/v1/memories/{memory_id}", delete_memory, methods=["DELETE"])
    app.add_api_route("/api/v1/memories/{memory_id}/feedback", memory_feedback, methods=["POST"])

    # --- Device, admin and operations routers ---
    app.include_router(build_device_router(kernel, auth_deps, stream_manager))
    app.include_router(build_client_router(get_current_user, kernel))
    app.include_router(build_admin_router(kernel, auth_deps, stream_manager))
    app.include_router(build_account_router(get_current_user))
    app.include_router(build_notification_router(get_current_user, auth_deps['get_device_principal']))
    app.include_router(build_workflow_router(kernel, get_current_user))
    app.include_router(build_rag_router(get_current_user))
    app.include_router(build_plugin_router(kernel, auth_deps["require_admin"], get_current_user))
    app.include_router(build_mcp_router(kernel, auth_deps["require_admin"], get_current_user))
    app.include_router(build_organization_router(get_current_user))
    app.include_router(build_storage_router(get_current_user))
    app.include_router(build_usage_router(auth_deps["require_admin"], get_current_user))
    app.include_router(build_update_router(auth_deps["require_admin"], get_current_user))
    app.include_router(build_approval_router(get_current_user, auth_deps["require_admin"]))
    app.include_router(build_generated_router(kernel, get_current_user, auth_deps["require_admin"]))
    plugin_manager = getattr(kernel, "plugin_manager", None)
    for plugin_id, plugin_router in (plugin_manager.collect_routers() if plugin_manager else []):
        app.include_router(plugin_router, prefix=f"/api/v1/ext/{plugin_id}")
    from .routes_insights import build_insights_router
    app.include_router(build_insights_router(kernel, get_current_user))
    return app
