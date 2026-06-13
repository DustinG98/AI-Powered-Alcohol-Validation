"""Runtime configuration loaded from environment variables.

Values are read once at import time. Pydantic isn't pulled in to keep the
dependency footprint minimal; a plain env-var read with a sensible default
is sufficient for this prototype.
"""

from __future__ import annotations

import os
import logging


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


# CORS: comma-separated list of allowed origins. "*" is the dev default.
ALLOWED_ORIGINS: list[str] = _split_csv(
    os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:8000")
)

# Uvicorn server config.
UVICORN_HOST: str = os.environ.get("UVICORN_HOST", "0.0.0.0")
UVICORN_PORT: int = int(os.environ.get("UVICORN_PORT", "8000"))
UVICORN_WORKERS: int = int(os.environ.get("UVICORN_WORKERS", "1"))
UVICORN_LOG_LEVEL: str = os.environ.get("UVICORN_LOG_LEVEL", "info").lower()

# Upload limits.
MAX_UPLOAD_SIZE_MB: int = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "15"))
MAX_BATCH_SIZE: int = int(os.environ.get("MAX_BATCH_SIZE", "25"))
MAX_UPLOAD_BYTES: int = MAX_UPLOAD_SIZE_MB * 1024 * 1024

# PaddleOCR env (already set in Dockerfile; allow override at runtime).
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "true")


def configure_logging() -> None:
    """Initialize root logger. Called from app.main on startup."""
    level = getattr(logging, UVICORN_LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
