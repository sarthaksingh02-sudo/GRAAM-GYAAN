"""
backend/main.py — FastAPI application entry point for GRAAM-GYAAN.
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.db import init_db

logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG", "false").lower() == "true" else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(
    title="GRAAM-GYAAN API",
    description="AI-powered rural welfare assistant — backend API",
    version="0.0.1",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    log.info("Starting GRAAM-GYAAN backend (MOCK=%s)", os.getenv("SARVAM_MOCK", "false"))
    init_db()


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "mock": os.getenv("SARVAM_MOCK", "false").lower() in ("1", "true")}
