"""FastAPI entry point for Yukiyasha."""

import json
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Any, TypeVar
from urllib.parse import quote, urlsplit

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
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
from yukiyasha.modules.memory import (
    MemoryError,
    MemoryLimitError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from yukiyasha.modules.primavtodor import (
    PrimavtodorError,
    PrintNotAvailableError,
    RecordInUseError,
    RecordNotFoundError,
    RecordValidationError,
    StatementError,
    UnknownEntityError,
    calendar_ru,
)
from yukiyasha.modules.primavtodor.settings import CONTROL_MODES, PRINT_FIELDS
from yukiyasha.modules.proposals import (
    ProposalError,
    ProposalNotFoundError,
    ProposalStateError,
    ProposalValidationError,
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


class MemoryWriteRequest(BaseModel):
    text: str


class SeasonRequest(BaseModel):
    season: str  # "summer" or "winter"


class TimesheetMarkRequest(BaseModel):
    month: str
    employee_id: str
    date: str
    code: str | None = None  # empty/None clears the manual mark


XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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
    if isinstance(exc, StatementError):
        return HTTPException(status_code=422, detail={"message": str(exc)})
    if isinstance(exc, PrintNotAvailableError):
        return HTTPException(status_code=422, detail={"message": exc.message})
    if isinstance(exc, RecordNotFoundError):
        return HTTPException(status_code=404, detail="Record not found")
    if isinstance(exc, UnknownEntityError):
        return HTTPException(status_code=404, detail="Unknown record kind")
    if isinstance(exc, DiskError):
        return disk_http_error(exc)
    return HTTPException(status_code=400, detail=str(exc))


def memory_http_error(exc: MemoryError | DiskError) -> HTTPException:
    """Map memory-domain failures to stable HTTP statuses."""
    if isinstance(exc, DiskError):
        return disk_http_error(exc)
    if isinstance(exc, MemoryNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, MemoryValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, MemoryLimitError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def proposal_http_error(exc: ProposalError) -> HTTPException:
    """Map proposal lifecycle failures to stable HTTP statuses."""
    if isinstance(exc, ProposalNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ProposalValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, ProposalStateError):
        return HTTPException(status_code=409, detail=str(exc))
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

    def memory_call(action: Callable[[], T]) -> T:
        if runtime.memory.state is not ModuleState.READY:
            raise HTTPException(status_code=503, detail="Memory module is not ready")
        try:
            return action()
        except (MemoryError, DiskError) as exc:
            raise memory_http_error(exc) from exc

    def proposal_call(action: Callable[[], T]) -> T:
        if runtime.proposals.state is not ModuleState.READY:
            raise HTTPException(status_code=503, detail="Proposal module is not ready")
        try:
            return action()
        except ProposalError as exc:
            raise proposal_http_error(exc) from exc

    def ai_call(action: Callable[[], T]) -> T:
        if runtime.ai.state is not ModuleState.READY:
            raise HTTPException(status_code=503, detail={"message": "Помощник не запущен"})
        try:
            return action()
        except (AiError, DiskError) as exc:
            raise ai_http_error(exc) from exc

    @application.get("/api/memory")
    def memory_list() -> dict[str, object]:
        return {"memories": memory_call(runtime.memory.list_items)}

    @application.get("/api/memory/search")
    def memory_search(q: str, limit: int = Query(default=5, ge=1, le=10)) -> dict[str, object]:
        return {
            "memories": memory_call(lambda: runtime.memory.search(q, limit=limit))
        }

    @application.post("/api/memory", status_code=201)
    def memory_remember(request: MemoryWriteRequest) -> dict[str, object]:
        return memory_call(lambda: runtime.memory.remember(request.text))

    @application.delete("/api/memory/{memory_id}")
    def memory_forget(memory_id: str) -> dict[str, str]:
        memory_call(lambda: runtime.memory.forget(memory_id))
        return {"status": "forgotten", "id": memory_id}

    @application.get("/api/proposals")
    def proposal_list(status: str | None = Query(default=None)) -> dict[str, object]:
        items = proposal_call(runtime.proposals.list_items)
        if status is not None:
            items = [item for item in items if item.get("status") == status]
        return {"proposals": items}

    @application.get("/api/proposals/{proposal_id}")
    def proposal_get(proposal_id: str) -> dict[str, object]:
        return proposal_call(lambda: runtime.proposals.get(proposal_id))

    @application.post("/api/proposals/{proposal_id}/approve")
    def proposal_approve(proposal_id: str) -> dict[str, object]:
        proposal = proposal_call(lambda: runtime.proposals.apply(proposal_id))
        if proposal.get("status") == "stale":
            raise HTTPException(status_code=409, detail=proposal)
        return proposal

    @application.post("/api/proposals/{proposal_id}/reject")
    def proposal_reject(proposal_id: str) -> dict[str, object]:
        return proposal_call(lambda: runtime.proposals.reject(proposal_id))

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

    @application.get("/api/primavtodor/month/{month}/review")
    def primavtodor_month_review(
        month: str, show_dismissed: bool = Query(default=False)
    ) -> dict[str, object]:
        """Steps, findings and readiness of a month (``ГГГГ-ММ``)."""
        return primavtodor_call(
            lambda: runtime.primavtodor.month_review(month, show_dismissed=show_dismissed)
        )

    @application.get("/api/primavtodor/month/{month}/package")
    def primavtodor_month_package(month: str) -> Response:
        """A zip with the timesheet, the analysis, the fuel cards and the findings."""
        content, name = primavtodor_call(lambda: runtime.primavtodor.month_package(month))
        return Response(
            content=content,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
        )

    @application.post("/api/primavtodor/findings/dismiss")
    def primavtodor_dismiss_finding(
        payload: Annotated[dict[str, Any], Body()],
    ) -> dict[str, object]:
        """Accept a finding: it stops counting until it is restored."""
        return primavtodor_call(
            lambda: runtime.primavtodor.dismiss_finding(
                str(payload.get("id", "")), str(payload.get("note", ""))
            )
        )

    @application.post("/api/primavtodor/findings/restore")
    def primavtodor_restore_finding(
        payload: Annotated[dict[str, Any], Body()],
    ) -> dict[str, object]:
        finding_id = str(payload.get("id", ""))
        return primavtodor_call(lambda: runtime.primavtodor.restore_finding(finding_id))

    @application.get("/api/primavtodor/calendar")
    def primavtodor_calendar_years() -> dict[str, object]:
        """Years of the production calendar that can be chosen."""
        return {"years": list(calendar_ru.available_years()), "labels": calendar_ru.KIND_LABELS}

    @application.get("/api/primavtodor/calendar/{year}")
    def primavtodor_calendar(year: int) -> dict[str, object]:
        view = calendar_ru.year_view(year)
        if view is None:
            raise HTTPException(
                status_code=404, detail={"message": f"Календаря на {year} год нет в программе"}
            )
        return view

    @application.get("/api/primavtodor/settings/print")
    def primavtodor_print_settings() -> dict[str, object]:
        """Organisation, signers and control wording printed on the waybill."""
        return {
            "values": primavtodor_call(runtime.primavtodor.settings.print_settings),
            "fields": [{"key": k, "label": v} for k, v in PRINT_FIELDS],
            "control_options": [{"value": k, "label": v} for k, v in CONTROL_MODES],
        }

    @application.put("/api/primavtodor/settings/print")
    def primavtodor_set_print_settings(payload: dict[str, object]) -> dict[str, str]:
        return primavtodor_call(lambda: runtime.primavtodor.settings.set_print_settings(payload))

    @application.post("/api/primavtodor/fuel/import")
    def primavtodor_import_fuel(
        content: Annotated[bytes, Body(media_type="application/octet-stream")],
        filename: str = Query(max_length=200),
        apply: bool = Query(default=False),
    ) -> dict[str, object]:
        """Match a fuel-card statement to waybills; ``apply=true`` creates the fuel records."""
        return primavtodor_call(
            lambda: runtime.primavtodor.import_fuel_statement(content, filename, apply=apply)
        )

    @application.get("/api/primavtodor/vehicles/{vehicle_id}/fuel-card")
    def primavtodor_fuel_card(vehicle_id: str, month: str = Query(max_length=7)) -> Response:
        """Monthly fuel card of a vehicle as an .xlsx (a sheet per driver)."""
        content, name = primavtodor_call(lambda: runtime.primavtodor.fuel_cards(vehicle_id, month))
        return Response(
            content=content,
            media_type=XLSX_TYPE,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
        )

    @application.get("/api/primavtodor/reports/fuel")
    def primavtodor_fuel_report(month: str = Query(max_length=7)) -> Response:
        """Monthly «Анализ расхода ГСМ» for all vehicles as an .xlsx."""
        content, name = primavtodor_call(lambda: runtime.primavtodor.fuel_report(month))
        return Response(
            content=content,
            media_type=XLSX_TYPE,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
        )

    @application.get("/api/primavtodor/waybills/{waybill_id}/print")
    def primavtodor_print_waybill(waybill_id: str) -> Response:
        content, name = primavtodor_call(lambda: runtime.primavtodor.print_waybill(waybill_id))
        return Response(
            content=content,
            media_type=XLSX_TYPE,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
        )

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

    @application.get("/api/primavtodor/timesheet/form")
    def primavtodor_timesheet_form(month: str = Query(max_length=7)) -> Response:
        """The month's timesheet filled into the form Т-12 as an .xlsx."""
        content, name = primavtodor_call(lambda: runtime.primavtodor.timesheet_form(month))
        return Response(
            content=content,
            media_type=XLSX_TYPE,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
        )

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
