"""Expose web app through legacy `apps.web` import path."""

from fomc.apps.web.main import app  # re-export for uvicorn

__all__ = ["app"]

