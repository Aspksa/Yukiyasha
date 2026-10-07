"""FastAPI entry point for Yukiyasha."""

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from yukiyasha.config import Settings
from yukiyasha.core import YukiyashaRuntime
from yukiyasha.modules.disk import (
    DiskConflictError,
    DiskDirectoryNotEmptyError,
    DiskEncodingError,
    DiskError,
    DiskPathError,
    DiskPermissionError,
    DiskSecurityError,
    DiskTooLargeError,
)
from yukiyasha.modules.registry import ModuleState
from yukiyasha.web.middleware import RequestBodyLimitMiddleware

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_REQUEST_BODY_BYTES = 2 * 1_048_576
ALLOWED_BROWSER_HOSTS = {"127.0.0.1", "localhost", "::1"}


class DiskWriteRequest(BaseModel):
    path: str
    content: str
    overwrite: bool = True


def create_app(settings: Settings | None = None) -> FastAPI:
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
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver", "[::1]"],
    )
    application.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)

    @application.middleware("http")
    async def protect_local_disk_api(request: Request, call_next):
        if request.url.path.startswith("/api/disk"):
            origin = request.headers.get("origin")
            if origin:
                origin_host = urlsplit(origin).hostname
                if origin_host not in ALLOWED_BROWSER_HOSTS:
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

    @application.get("/api/disk")
    def disk_list(path: str = Query(default="")) -> dict[str, object]:
        require_disk_ready()
        try:
            return {"path": path, "entries": runtime.disk.list_entries(path)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Directory not found") from exc
        except NotADirectoryError as exc:
            raise HTTPException(status_code=400, detail="Path is not a directory") from exc
        except DiskPermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (DiskSecurityError, DiskPathError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DiskError as exc:
            raise HTTPException(status_code=500, detail="Filesystem operation failed") from exc

    @application.get("/api/disk/file")
    def disk_read(path: str) -> dict[str, str]:
        require_disk_ready()
        try:
            return {"path": path, "content": runtime.disk.read_text(path)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="File not found") from exc
        except IsADirectoryError as exc:
            raise HTTPException(status_code=400, detail="Path is a directory") from exc
        except DiskPermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except DiskTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except (DiskSecurityError, DiskPathError, DiskEncodingError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DiskError as exc:
            raise HTTPException(status_code=500, detail="Filesystem operation failed") from exc

    @application.put("/api/disk/file")
    def disk_write(request: DiskWriteRequest) -> dict[str, object]:
        require_disk_ready()
        try:
            runtime.disk.write_text(request.path, request.content, overwrite=request.overwrite)
            return {"status": "ok", "path": request.path}
        except DiskPermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except DiskTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except DiskConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (DiskSecurityError, DiskPathError, DiskEncodingError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DiskError as exc:
            raise HTTPException(status_code=500, detail="Filesystem operation failed") from exc

    @application.delete("/api/disk/file")
    def disk_delete(path: str) -> dict[str, str]:
        require_disk_ready()
        try:
            runtime.disk.delete(path)
            return {"status": "ok", "path": path}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="File not found") from exc
        except DiskPermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except DiskDirectoryNotEmptyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (DiskSecurityError, DiskPathError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DiskError as exc:
            raise HTTPException(status_code=500, detail="Filesystem operation failed") from exc

    return application


app = create_app()
