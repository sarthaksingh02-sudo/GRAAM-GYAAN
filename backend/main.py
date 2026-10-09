"""
backend/main.py — FastAPI application entry point for GRAAM-GYAAN.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.db import init_db
from backend.routers import consent, documents, export, family, knowledge, voice

BASE_DIR = Path(__file__).resolve().parent.parent

logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG", "false").lower() == "true" else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting GRAAM-GYAAN backend (MOCK=%s)", os.getenv("SARVAM_MOCK", "false"))
    init_db()
    yield

app = FastAPI(
    title="GRAAM-GYAAN API",
    description="AI-powered rural welfare assistant — Phase 4 Export & PWA Polish",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Include Routers
app.include_router(consent.router)
app.include_router(documents.router)
app.include_router(family.router)
app.include_router(voice.router)
app.include_router(knowledge.router)
app.include_router(export.router)

# Mount frontend public directory
frontend_dir = BASE_DIR / "frontend" / "public"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(frontend_dir / "index.html")

    @app.get("/style.css")
    async def serve_css():
        return FileResponse(frontend_dir / "style.css")

    @app.get("/app.js")
    async def serve_js():
        return FileResponse(frontend_dir / "app.js")

    @app.get("/manifest.json")
    async def serve_manifest():
        return FileResponse(frontend_dir / "manifest.json")

    @app.get("/sw.js")
    async def serve_sw():
        return FileResponse(frontend_dir / "sw.js")


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "status": "ok",
        "mock": os.getenv("SARVAM_MOCK", "false").lower() in ("1", "true"),
        "service": "GRAAM-GYAAN Backend",
        "phase": 4,
    }
