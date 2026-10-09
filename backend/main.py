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
    allow_origins=[x.strip() for x in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173,http://127.0.0.1:8000").split(",") if x.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-User-Id"],
)

@app.middleware("http")
async def household_session(request, call_next):
    from backend.active_user import public_mode, device_key
    import secrets, hashlib, re
    if not public_mode():
        return await call_next(request)
    secret = request.cookies.get("gg_session", "")
    fresh = not re.fullmatch(r"[a-f0-9]{64}", secret)
    if fresh:
        secret = secrets.token_hex(32)
    token = device_key.set(hashlib.sha256(secret.encode()).hexdigest())
    try:
        response = await call_next(request)
        if fresh:
            response.set_cookie("gg_session", secret, max_age=60*60*24*90, httponly=True, secure=True, samesite="lax", path="/")
        if request.url.path.startswith("/api/") and request.url.path not in {"/api/catalog/schemes", "/api/languages", "/api/intents", "/api/home-tiles"}:
            response.headers["Cache-Control"] = "private, no-store"
        return response
    finally:
        device_key.reset(token)

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
frontend_dir = BASE_DIR / "frontend" / "dist"
if not frontend_dir.exists():
    frontend_dir = BASE_DIR / "frontend" / "public"
if frontend_dir.exists():
    if (frontend_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(frontend_dir / "assets")), name="assets")
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

    @app.get("/")
    @app.get("/index.html")
    async def serve_index():
        if not (frontend_dir / "index.html").exists():
            from fastapi.responses import HTMLResponse
            return HTMLResponse("<h1>GRAAM-GYAAN</h1><p>Build the frontend: cd frontend &amp;&amp; npm install &amp;&amp; npm run build. Then restart the backend.</p>", status_code=503)
        return FileResponse(frontend_dir / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/icon-{size}.png")
    async def serve_icon(size: int):
        from fastapi import HTTPException
        if size not in (192, 512):
            raise HTTPException(404)
        return FileResponse(frontend_dir / f"icon-{size}.png")

    @app.get("/manifest.json")
    async def serve_manifest():
        return FileResponse(frontend_dir / "manifest.json")

    @app.get("/sw.js")
    async def serve_sw():
        return FileResponse(frontend_dir / "sw.js", headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
async def healthz() -> dict:
    from backend.sarvam_client import SarvamClient
    client = SarvamClient()
    return {
        "status": "ok",
        "ephemeralStorage": os.getenv("EPHEMERAL_STORAGE") == "true",
        "mock": client.mock,
        "mode": client.mode,
        "aiConfigured": client.mode != "unconfigured",
        "aiVerified": False,
        "service": "GRAAM-GYAAN Backend",
        "phase": 4,
    }
