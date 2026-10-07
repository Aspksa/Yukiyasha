"""FastAPI entry point for Yukiyasha."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from yukiyasha.config import Settings
from yukiyasha.core import YukiyashaRuntime
from yukiyasha.modules.disk import DiskSecurityError

STATIC_DIR = Path(__file__).resolve().parent / "static"
settings = Settings.from_env()
runtime = YukiyashaRuntime(settings)


class DiskWriteRequest(BaseModel):
    path: str
    content: str
    overwrite: bool = True


@asynccontextmanager
async def lifespan(_: FastAPI):
    runtime.start()
    yield
    runtime.stop()


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Yukiyasha core API",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    snapshot = runtime.snapshot()
    return {
        "status": "ok" if snapshot.state.value == "ready" else snapshot.state.value,
        "service": snapshot.name,
        "version": snapshot.version,
    }


@app.get("/api/runtime")
async def runtime_state() -> dict[str, str]:
    return runtime.snapshot().to_dict()


@app.get("/api/modules")
async def modules() -> list[dict[str, object]]:
    return runtime.modules.snapshots()


@app.get("/api/disk")
async def disk_list(path: str = Query(default="")) -> dict[str, object]:
    try:
        return {"path": path, "entries": runtime.disk.list_entries(path)}
    except (DiskSecurityError, FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/disk/file")
async def disk_read(path: str) -> dict[str, str]:
    try:
        return {"path": path, "content": runtime.disk.read_text(path)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    except (DiskSecurityError, IsADirectoryError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/disk/file")
async def disk_write(request: DiskWriteRequest) -> dict[str, object]:
    try:
        runtime.disk.write_text(request.path, request.content, overwrite=request.overwrite)
        return {"status": "ok", "path": request.path}
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="File already exists") from exc
    except (DiskSecurityError, IsADirectoryError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/disk/file")
async def disk_delete(path: str) -> dict[str, str]:
    try:
        runtime.disk.delete(path)
        return {"status": "ok", "path": path}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    except OSError as exc:
        raise HTTPException(status_code=409, detail="Directory is not empty") from exc
    except DiskSecurityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
