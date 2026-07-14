import logging
import os

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.api import drift, health, scan
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)1.1s %(asctime)s %(pathname)s:%(lineno)d] %(message)s",
    datefmt="%y%m%d %H:%M:%S",
)
app = FastAPI(title="Driftwatch")

# API v1 routes under /api/v1 prefix
api_router = APIRouter(prefix=settings.API_V1_STR)
api_router.include_router(drift.router)
api_router.include_router(scan.router)
app.include_router(api_router)

# Health check at /health (no prefix)
app.include_router(health.router)

# HTTP RED metrics (Rate, Errors, Duration). Exclude /metrics so scrapes
# do not inflate their own request counters.
Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(
    app, endpoint="/metrics", include_in_schema=False
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

if os.path.exists("/app/frontend"):
    app.mount("/static", StaticFiles(directory="/app/frontend"), name="static")


@app.get("/")
def serve_dashboard():
    index = "/app/frontend/index.html"
    if not os.path.exists(index):
        return {
            "error": "Dashboard not found",
            "hint": "frontend/index.html missing from image",
        }
    return FileResponse(index)
