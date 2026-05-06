from __future__ import annotations

import re
import shutil
from pathlib import Path

from src.config import settings
from src.db.schemas import MediaItem, _RumorSampleIn

_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


def read_markdown_sample(md_path: Path) -> tuple[_RumorSampleIn, list[MediaItem] | None, str]:
    """Read markdown and build sample/media payloads for analysis."""
    raw_text = md_path.read_text(encoding="utf-8").strip()
    sample = _RumorSampleIn(raw_text=raw_text, title=md_path.stem)
    media_items = extract_md_images(md_path) or None
    return sample, media_items, raw_text


def extract_md_images(md_path: Path) -> list[MediaItem]:
    """Parse markdown image references and normalize them into media items."""
    text = md_path.read_text(encoding="utf-8")
    media_dir = Path(settings.MEDIA_DIR).resolve()
    media_dir.mkdir(exist_ok=True)

    items: list[MediaItem] = []
    seen: set[str] = set()
    for caption, img_ref in _MD_IMAGE_RE.findall(text):
        img_path = (md_path.parent / img_ref).resolve()
        if not img_path.is_file() or img_path.suffix.lower() not in _IMAGE_EXTS:
            continue

        try:
            rel = img_path.relative_to(media_dir)
        except ValueError:
            dest = media_dir / img_path.name
            if not dest.exists():
                shutil.copy2(img_path, dest)
            rel = dest.relative_to(media_dir)

        rel_posix = str(rel).replace("\\", "/")
        if rel_posix in seen:
            continue
        seen.add(rel_posix)

        items.append(MediaItem(type="image", path=rel_posix, caption=caption))

    return items
