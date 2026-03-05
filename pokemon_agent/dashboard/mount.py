"""FastAPI dashboard mounting for the Hermes Plays Pokémon dashboard."""

from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def mount_dashboard(app):
    """Mount the dashboard static files on /dashboard.

    Args:
        app: FastAPI application instance.

    The dashboard serves a single-page streaming command center
    at /dashboard that connects to the API via WebSocket and polling.
    """
    try:
        from fastapi.staticfiles import StaticFiles
    except ImportError:
        logger.warning(
            "FastAPI not installed. Install with: pip install pokemon-agent[dashboard]"
        )
        return

    if not STATIC_DIR.exists():
        logger.error(f"Dashboard static directory not found: {STATIC_DIR}")
        return

    app.mount(
        "/dashboard",
        StaticFiles(directory=str(STATIC_DIR), html=True),
        name="dashboard",
    )
    logger.info("Dashboard mounted at /dashboard")


def get_dashboard_routes(app):
    """Register additional dashboard API routes if needed.

    Args:
        app: FastAPI application instance.
    """
    try:
        from fastapi import APIRouter
        from fastapi.responses import RedirectResponse
    except ImportError:
        return

    router = APIRouter()

    @router.get("/")
    async def root_redirect():
        """Redirect root to dashboard."""
        return RedirectResponse(url="/dashboard")

    app.include_router(router)
