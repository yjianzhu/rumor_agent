from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx

from src.config import settings


def _media_dir() -> Path:
    return Path(settings.MEDIA_DIR)


def save_image(data: bytes, slug: str, filename: str) -> str:
    """Save raw image bytes to media/<slug>/filename, return relative path."""
    dest = _media_dir() / slug / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return f"media/{slug}/{filename}"


def save_image_from_url(url: str, slug: str) -> str:
    """Download a remote image and save it locally, return relative path."""
    resp = httpx.get(url, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    filename = Path(urlparse(url).path).name or "image"
    return save_image(resp.content, slug, filename)
