"""NxtWave Breakpoint - AI Failure Lab API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.client import is_configured, provider_status
from app.auth.oidc import status as auth_status
from app.config import settings
from app.db import SessionLocal, init_db
from app.routers import admin, attempts, auth, debate, stats, subjects
from app.seed import seed_from_content, seed_templates

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("breakpoint")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as session:
        summary = seed_from_content(session)
        templates = seed_templates(session)
    logger.info("content: %s | templates added: %d", summary, templates)
    if not is_configured():
        logger.warning(
            "No AI provider configured. Pre-generated challenges serve normally; "
            "generation, evidence evaluation, debate and live debrief are "
            "unavailable. Set BREAKPOINT_OPENROUTER_API_KEY or ANTHROPIC_API_KEY."
        )
    else:
        logger.info("AI provider: %s", provider_status())
    yield


app = FastAPI(
    title="NxtWave Breakpoint",
    description="AI Failure Lab - AI says it's right. Prove it.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(subjects.router, prefix="/api")
app.include_router(attempts.router, prefix="/api")
app.include_router(debate.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(admin.router, prefix="/api")


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "ai_configured": is_configured(),
        "ai": provider_status(),
        # Identity is an adapter, so its state belongs in health rather than
        # in a comment: an operator must be able to see whether SSO is live
        # without reading the code (PRD v0.2 section 12.5).
        "auth": auth_status(),
        "quality_threshold": settings.quality_threshold,
        "max_debate_turns": settings.max_debate_turns,
    }
