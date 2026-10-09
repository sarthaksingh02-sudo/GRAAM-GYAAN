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
from backend.routers import consent, documents, family

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
    description="AI-powered rural welfare assistant — Phase 1 Document to Profile API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(consent.router)
app.include_router(documents.router)
app.include_router(family.router)


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "status": "ok",
        "mock": os.getenv("SARVAM_MOCK", "false").lower() in ("1", "true"),
        "service": "GRAAM-GYAAN Backend",
        "phase": 1,
    }
