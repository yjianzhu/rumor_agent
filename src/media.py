from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx

from src.config import settings


def _media_dir() -> Path:
    return Path(settings.MEDIA_DIR)


def save_image(data: bytes, slug: str, filename: str) -> str:
    """Save raw image bytes to ``<MEDIA_DIR>/<slug>/<filename>``.

    Returns the path **relative to MEDIA_DIR** (e.g. ``"<slug>/<filename>"``).
    Templates render it as ``<img src="/media/{{ item.path }}">``; the FastAPI
    static mount on ``/media`` already maps to ``MEDIA_DIR``.

    Both ``slug`` and ``filename`` are reduced to basename to prevent path
    traversal — callers cannot escape the configured ``MEDIA_DIR``.
    """
    safe_slug = Path(slug).name
    safe_filename = Path(filename).name
    if not safe_slug or not safe_filename:
        raise ValueError(f"Invalid slug or filename: slug={slug!r} filename={filename!r}")

    dest = _media_dir() / safe_slug / safe_filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return f"{safe_slug}/{safe_filename}"


def save_image_from_url(url: str, slug: str) -> str:
    """Download a remote image and save it locally, return relative path."""
    resp = httpx.get(url, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    filename = Path(urlparse(url).path).name or "image"
    return save_image(resp.content, slug, filename)
