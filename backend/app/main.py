import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from app.api import drift, health, scan


logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)1.1s %(asctime)s %(pathname)s:%(lineno)d] %(message)s",
    datefmt="%y%m%d %H:%M:%S",
)
app = FastAPI(title="Driftwatch")
app.include_router(health.router)
app.include_router(drift.router)
app.include_router(scan.router)


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
    return FileResponse("/app/frontend/index.html")
