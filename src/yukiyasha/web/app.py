"""FastAPI entry point for Yukiyasha."""

import json
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Any, TypeVar
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.middleware.trustedhost import TrustedHostMiddleware

from yukiyasha.config import Settings
from yukiyasha.core import YukiyashaRuntime
from yukiyasha.modules.ai import (
    AiBusyError,
    AiError,
    AiNotConfiguredError,
    ChatTurn,
    ConversationNotFoundError,
    MessageRejectedError,
    ProviderError,
)
from yukiyasha.modules.disk import (
    DiskConflictError,
    DiskEncodingError,
    DiskError,
    DiskNotReadyError,
    DiskPathError,
    DiskPermissionError,
    DiskSecurityError,
    DiskTooLargeError,
)
from yukiyasha.modules.primavtodor import (
    PrimavtodorError,
    RecordInUseError,
    RecordNotFoundError,
    RecordValidationError,
    UnknownEntityError,
)
from yukiyasha.modules.registry import ModuleState
from yukiyasha.web.middleware import RequestBodyLimitMiddleware, SecurityHeadersMiddleware

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_REQUEST_BODY_BYTES = 2 * 1_048_576
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


class DiskWriteRequest(BaseModel):
    path: str
    content: str
    overwrite: bool = True


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class PersonaRequest(BaseModel):
    text: str


class SeasonRequest(BaseModel):
    season: str  # "summer" or "winter"


class TimesheetMarkRequest(BaseModel):
    month: str
    employee_id: str
    date: str
    code: str | None = None  # empty/None clears the manual mark


T = TypeVar("T")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _is_same_origin(origin: str, request: Request) -> bool:
    parts = urlsplit(origin)
    host = request.headers.get("host", "")
    return parts.scheme == request.url.scheme and parts.netloc.lower() == host.lower()


def disk_http_error(exc: DiskError) -> HTTPException:
    """Map a disk-domain error to one consistent HTTP status."""
    if isinstance(exc, DiskNotReadyError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, DiskPermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, DiskTooLargeError):
        return HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, DiskConflictError):  # includes DiskDirectoryNotEmptyError
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, DiskSecurityError | DiskPathError | DiskEncodingError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Filesystem operation failed")


def primavtodor_http_error(exc: PrimavtodorError | DiskError) -> HTTPException:
    """Map a Примавтодор (or underlying disk) error to one consistent HTTP status."""
    if isinstance(exc, RecordValidationError):
        return HTTPException(
            status_code=422, detail={"message": exc.message, "fields": exc.fields}
        )
    if isinstance(exc, RecordInUseError):
        return HTTPException(
            status_code=409, detail={"message": exc.message, "references": exc.references}
        )
    if isinstance(exc, RecordNotFoundError):
        return HTTPException(status_code=404, detail="Record not found")
    if isinstance(exc, UnknownEntityError):
        return HTTPException(status_code=404, detail="Unknown record kind")
    if isinstance(exc, DiskError):
        return disk_http_error(exc)
    return HTTPException(status_code=400, detail=str(exc))


def ai_http_error(exc: AiError | DiskError) -> HTTPException:
    """Map an AI-module (or underlying disk) error to one consistent HTTP status."""
    if isinstance(exc, DiskError):
        return disk_http_error(exc)
    detail: dict[str, object] = {"message": exc.message}
    if isinstance(exc, ConversationNotFoundError):
        return HTTPException(status_code=404, detail=detail)
    if isinstance(exc, MessageRejectedError):
        return HTTPException(status_code=422, detail=detail)
    if isinstance(exc, AiNotConfiguredError):
        return HTTPException(status_code=503, detail={**detail, "code": "not_configured"})
    if isinstance(exc, AiBusyError):
        return HTTPException(status_code=429, detail=detail)
    if isinstance(exc, ProviderError):
        return HTTPException(status_code=502, detail={**detail, "provider_status": exc.status})
    return HTTPException(status_code=400, detail=detail)


def _sse(event: dict[str, object]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _chat_events(turn: ChatTurn) -> Iterator[str]:
    """Server-sent events of one answer; a mid-stream failure becomes an ``error`` event."""
    try:
        for event in turn.events():
            yield _sse(event)
    except AiError as exc:
        yield _sse({"type": "error", "message": exc.message})
    except Exception:  # never leak internals (or a key) to the browser
        yield _sse({"type": "error", "message": "Неожиданная ошибка при получении ответа"})


def create_app(
    settings: Settings | None = None, *, extra_allowed_hosts: tuple[str, ...] = ()
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    runtime = YukiyashaRuntime(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        runtime.start()
        try:
            yield
        finally:
            runtime.stop()

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.version,
        description="Yukiyasha core API",
        lifespan=lifespan,
        debug=resolved_settings.debug,
    )
    application.state.runtime = runtime
    application.add_middleware(
        TrustedHostMiddleware, allowed_hosts=[*LOCAL_HOSTS, *extra_allowed_hosts]
    )
    application.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)
    application.add_middleware(SecurityHeadersMiddleware)

    @application.middleware("http")
    async def protect_local_disk_api(request: Request, call_next):
        path = request.url.path
        # Disk reads are protected too (file content), every other API only when it changes data.
        protected = path.startswith("/api/disk") or (
            path.startswith("/api/") and request.method not in SAFE_METHODS
        )
        if protected:
            origin = request.headers.get("origin")
            # The UI is served from this very origin, so anything else (another site, or
            # another local app on a different port) is a cross-origin request.
            if origin and not _is_same_origin(origin, request):
                return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
        return await call_next(request)

    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def require_disk_ready() -> None:
        if runtime.disk.state is not ModuleState.READY:
            raise HTTPException(status_code=503, detail="Yukiyasha Disk is not ready")

    @application.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/api/health")
    def health() -> dict[str, str]:
        snapshot = runtime.snapshot()
        return {
            "status": "ok" if snapshot.state.value == "ready" else snapshot.state.value,
            "service": snapshot.name,
            "version": snapshot.version,
        }

    @application.get("/api/runtime")
    def runtime_state() -> dict[str, str | None]:
        return runtime.snapshot().to_dict()

    @application.get("/api/modules")
    def modules() -> list[dict[str, object]]:
        return runtime.modules.snapshots()

    @application.get("/api/primavtodor/sections")
    def primavtodor_sections() -> list[dict[str, object]]:
        if runtime.primavtodor.state is not ModuleState.READY:
            raise HTTPException(status_code=503, detail="Primavtodor module is not ready")
        try:
            return runtime.primavtodor.section_summaries()
        except DiskError as exc:
            raise disk_http_error(exc) from exc

    def primavtodor_call(action: Callable[[], T]) -> T:
        if runtime.primavtodor.state is not ModuleState.READY:
            raise HTTPException(status_code=503, detail="Primavtodor module is not ready")
        try:
            return action()
        except (PrimavtodorError, DiskError) as exc:
            raise primavtodor_http_error(exc) from exc

    def ai_call(action: Callable[[], T]) -> T:
        if runtime.ai.state is not ModuleState.READY:
            raise HTTPException(status_code=503, detail={"message": "Помощник не запущен"})
        try:
            return action()
        except (AiError, DiskError) as exc:
            raise ai_http_error(exc) from exc

    @application.get("/api/ai/status")
    def ai_status() -> dict[str, object]:
        return runtime.ai.status()

    @application.get("/api/ai/persona")
    def ai_persona() -> dict[str, str]:
        return {"text": ai_call(runtime.ai.persona)}

    @application.put("/api/ai/persona")
    def ai_set_persona(request: PersonaRequest) -> dict[str, str]:
        ai_call(lambda: runtime.ai.set_persona(request.text))
        return {"status": "ok"}

    @application.get("/api/ai/conversations")
    def ai_conversations() -> dict[str, object]:
        return {"conversations": ai_call(runtime.ai.list_chats)}

    @application.get("/api/ai/conversations/{chat_id}")
    def ai_conversation(chat_id: str) -> dict[str, object]:
        return ai_call(lambda: runtime.ai.get_chat(chat_id))

    @application.delete("/api/ai/conversations/{chat_id}")
    def ai_delete_conversation(chat_id: str) -> dict[str, str]:
        ai_call(lambda: runtime.ai.delete_chat(chat_id))
        return {"status": "ok", "id": chat_id}

    @application.post("/api/ai/chat")
    def ai_chat(request: ChatRequest) -> StreamingResponse:
        """Stream the answer as server-sent events: meta, delta..., done (or error)."""
        turn = ai_call(lambda: runtime.ai.begin_chat(request.conversation_id, request.message))
        return StreamingResponse(
            _chat_events(turn),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
            background=BackgroundTask(turn.release),
        )

    @application.get("/api/primavtodor/schema")
    def primavtodor_schema() -> dict[str, object]:
        return runtime.primavtodor.schema()

    @application.get("/api/primavtodor/settings")
    def primavtodor_settings() -> dict[str, object]:
        return primavtodor_call(runtime.primavtodor.settings.load)

    @application.put("/api/primavtodor/settings/season")
    def primavtodor_set_season(request: SeasonRequest) -> dict[str, object]:
        """One switch for every fuel norm: summer or winter."""
        return primavtodor_call(lambda: runtime.primavtodor.data.apply_season(request.season))

    @application.get("/api/primavtodor/records/{kind}")
    def primavtodor_list(kind: str) -> dict[str, object]:
        return primavtodor_call(lambda: runtime.primavtodor.data.list_records(kind))

    @application.post("/api/primavtodor/records/{kind}", status_code=201)
    def primavtodor_create(
        kind: str, payload: Annotated[dict[str, Any], Body()]
    ) -> dict[str, object]:
        return primavtodor_call(lambda: runtime.primavtodor.data.create(kind, payload))

    @application.get("/api/primavtodor/records/{kind}/{record_id}")
    def primavtodor_get(kind: str, record_id: str) -> dict[str, object]:
        return primavtodor_call(lambda: runtime.primavtodor.data.get(kind, record_id))

    @application.put("/api/primavtodor/records/{kind}/{record_id}")
    def primavtodor_update(
        kind: str, record_id: str, payload: Annotated[dict[str, Any], Body()]
    ) -> dict[str, object]:
        return primavtodor_call(lambda: runtime.primavtodor.data.update(kind, record_id, payload))

    @application.delete("/api/primavtodor/records/{kind}/{record_id}")
    def primavtodor_delete(kind: str, record_id: str) -> dict[str, str]:
        primavtodor_call(lambda: runtime.primavtodor.data.delete(kind, record_id))
        return {"status": "ok", "id": record_id}

    @application.get("/api/primavtodor/timesheet")
    def primavtodor_timesheet(month: str | None = Query(default=None)) -> dict[str, object]:
        wanted = month or date.today().strftime("%Y-%m")
        return primavtodor_call(lambda: runtime.primavtodor.timesheet.month_view(wanted))

    @application.put("/api/primavtodor/timesheet/mark")
    def primavtodor_timesheet_mark(request: TimesheetMarkRequest) -> dict[str, object]:
        return primavtodor_call(
            lambda: runtime.primavtodor.timesheet.set_mark(
                request.month, request.employee_id, request.date, request.code
            )
        )

    @application.get("/api/disk")
    def disk_list(path: str = Query(default="")) -> dict[str, object]:
        require_disk_ready()
        try:
            return {"path": path, "entries": runtime.disk.list_entries(path)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Directory not found") from exc
        except NotADirectoryError as exc:
            raise HTTPException(status_code=400, detail="Path is not a directory") from exc
        except DiskError as exc:
            raise disk_http_error(exc) from exc

    @application.get("/api/disk/file")
    def disk_read(path: str) -> dict[str, str]:
        require_disk_ready()
        try:
            return {"path": path, "content": runtime.disk.read_text(path)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="File not found") from exc
        except IsADirectoryError as exc:
            raise HTTPException(status_code=400, detail="Path is a directory") from exc
        except DiskError as exc:
            raise disk_http_error(exc) from exc

    @application.put("/api/disk/file")
    def disk_write(request: DiskWriteRequest) -> dict[str, object]:
        require_disk_ready()
        try:
            runtime.disk.write_text(request.path, request.content, overwrite=request.overwrite)
            return {"status": "ok", "path": request.path}
        except DiskError as exc:
            raise disk_http_error(exc) from exc

    @application.delete("/api/disk/file")
    def disk_delete(path: str) -> dict[str, str]:
        require_disk_ready()
        try:
            runtime.disk.delete(path)
            return {"status": "ok", "path": path}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="File not found") from exc
        except DiskError as exc:
            raise disk_http_error(exc) from exc

    return application


app = create_app()
