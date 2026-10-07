"""FastAPI entry point for Yukiyasha."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from yukiyasha.config import Settings
from yukiyasha.core import YukiyashaRuntime

STATIC_DIR = Path(__file__).resolve().parent / "static"
settings = Settings.from_env()
runtime = YukiyashaRuntime(settings)


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
