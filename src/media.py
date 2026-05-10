from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image

from src.config import settings


def _media_dir() -> Path:
    return Path(settings.MEDIA_DIR)


@lru_cache(maxsize=1)
def _seal_image() -> Image.Image:
    seal_path = Path(__file__).resolve().parent / "api" / "static" / "seal.png"
    with Image.open(seal_path) as im:
        return im.convert("RGBA")


def stamp_rumor_image(data: bytes, content_type: str) -> bytes:
    """Return image bytes with the rumor seal burned into the center of the image."""
    if content_type == "image/gif":
        raise ValueError("谣言 GIF 暂不支持自动盖章")

    with Image.open(BytesIO(data)) as im:
        base_format = im.format
        base = im.convert("RGBA")

    seal = _seal_image()
    max_w = max(1, int(base.width * 0.5))
    max_h = max(1, int(base.height * 0.5))
    scale = min(max_w / seal.width, max_h / seal.height)
    seal = seal.resize(
        (max(1, int(seal.width * scale)), max(1, int(seal.height * scale))),
        Image.Resampling.LANCZOS,
    )
    base.alpha_composite(seal, ((base.width - seal.width) // 2, (base.height - seal.height) // 2))

    out = BytesIO()
    if content_type == "image/jpeg":
        base.convert("RGB").save(out, format="JPEG", quality=92, optimize=True)
    elif content_type == "image/webp":
        base.save(out, format="WEBP", quality=92, method=4)
    else:
        base.save(out, format=base_format or "PNG", optimize=True)
    return out.getvalue()


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
