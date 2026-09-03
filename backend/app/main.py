"""FastAPI application entry point.

Run locally with:
    uvicorn app.main:app --reload --port 8000

On startup we open the shared MongoDB connection (and fail fast if the database
isn't reachable); on shutdown we close it. Interactive API docs live at /docs.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from . import mongodb
from .config import settings
from .routers import auth, insights, sync, transactions

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: connect to MongoDB (raises if unreachable -> app won't boot silently).
    await mongodb.connect()
    yield
    # Shutdown: release the connection cleanly.
    await mongodb.disconnect()


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)

# The Streamlit frontend runs on a different origin, so it needs CORS access.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(sync.router)
app.include_router(transactions.router)
app.include_router(insights.router)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    """Liveness + MongoDB connectivity check."""
    detail = "connected"
    healthy = True
    try:
        await mongodb.get_db().command("ping")
    except Exception as exc:  # surface the real reason, don't hide it
        healthy = False
        detail = str(exc)
    return {
        "status": "ok" if healthy else "degraded",
        "app": settings.app_name,
        "mongodb": detail,
    }


@app.get("/", tags=["meta"])
async def root() -> dict:
    return {"name": settings.app_name, "docs": "/docs", "health": "/health"}
