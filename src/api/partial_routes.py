from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from src.api.deps import get_db_session, make_templates, resolve_view
from src.db.crud import (
    add_media_files,
    count_by_status,
    count_published,
    count_recent,
    count_rumors,
    count_rumors_filtered,
    get_rumor_by_slug,
    get_rumor_detail_by_slug,
    list_rumors,
    remove_media_file,
    update_rumor,
)
from src.db.models import RumorStatus
from src.db.schemas import RumorUpdate
from src.media import save_image

templates = make_templates()

router = APIRouter(prefix="/admin/partials")

DEFAULT_LIMIT = 20


@router.get("/rumors", response_class=HTMLResponse)
def rumor_list_partial(
    request: Request,
    q: str = "",
    status: str = "",
    tag: str = "",
    view: str = "pending",
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    db: Session = Depends(get_db_session),
):
    status_enum = RumorStatus(status) if status else None
    canonical_view, is_published = resolve_view(view)

    rumors = list_rumors(
        db,
        status=status_enum,
        tag=tag or None,
        q=q or None,
        is_published=is_published,
        offset=offset,
        limit=limit,
        include_analysis=True,
    )

    total = count_rumors_filtered(
        db, status=status_enum, tag=tag or None, q=q or None,
        is_published=is_published,
    )

    return templates.TemplateResponse(request, "partials/rumor_list.html", {
        "rumors": rumors,
        "total": total,
        "has_more": offset + limit < total,
        "next_offset": offset + limit,
        "limit": limit,
        "q": q,
        "status": status,
        "tag": tag,
        "view": canonical_view,
    })


@router.get("/rumors/{slug}", response_class=HTMLResponse)
def rumor_detail_partial(
    request: Request,
    slug: str,
    db: Session = Depends(get_db_session),
):
    rumor = get_rumor_detail_by_slug(db, slug)
    if rumor is None:
        raise HTTPException(status_code=404, detail="Rumor not found")
    return templates.TemplateResponse(request, "partials/rumor_detail.html", {
        "rumor": rumor,
    })


@router.post("/rumors/{slug}/review", response_class=HTMLResponse)
def rumor_review_partial(
    request: Request,
    slug: str,
    title: str = Form(...),
    summary: str = Form(""),
    rumor_content: str = Form(""),
    status: RumorStatus = Form(...),
    truth_content: str = Form(""),
    is_published: bool = Form(False),
    db: Session = Depends(get_db_session),
):
    """Form-friendly review submission. Updates the rumor and returns the refreshed article partial."""
    rumor = get_rumor_by_slug(db, slug)
    if rumor is None:
        raise HTTPException(status_code=404, detail="Rumor not found")

    title = title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title cannot be empty")

    update_rumor(db, rumor.id, RumorUpdate(
        title=title,
        summary=summary.strip() or None,
        rumor_content=rumor_content.strip() or None,
        status=status,
        truth_content=truth_content.strip() or None,
        is_published=is_published,
    ))

    refreshed = get_rumor_detail_by_slug(db, slug)
    return templates.TemplateResponse(request, "partials/rumor_detail.html", {
        "rumor": refreshed,
    })


@router.get("/stats", response_class=HTMLResponse)
def stats_partial(
    request: Request,
    db: Session = Depends(get_db_session),
):
    stats = {
        "total": count_rumors(db),
        "by_status": count_by_status(db),
        "published": count_published(db),
        "recent_7d": count_recent(db),
    }
    return templates.TemplateResponse(request, "partials/stats_bar.html", {
        "stats": stats,
    })


# ─── Media manager (审核台图片素材上传/删除) ────────────────────────────────

import io
import re
import time
from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB
ALLOWED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MEDIA_IMAGE_LABELS = {"rumor", "debunk"}
_EXT_BY_MIME = {
    "image/png": ".png", "image/jpeg": ".jpg",
    "image/webp": ".webp", "image/gif": ".gif",
}


def _safe_filename_stem(name: str) -> str:
    """Return a slug-safe filename stem from the user-provided name."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "img"
    return stem[:60]


def _render_media_manager(request: Request, rumor, error: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(request, "partials/media_manager.html", {
        "rumor": rumor,
        "error": error,
        "max_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
    })


@router.get("/rumors/{slug}/media", response_class=HTMLResponse)
def media_manager_partial(
    request: Request,
    slug: str,
    db: Session = Depends(get_db_session),
):
    rumor = get_rumor_by_slug(db, slug)
    if rumor is None:
        raise HTTPException(status_code=404, detail="Rumor not found")
    return _render_media_manager(request, rumor)


@router.post("/rumors/{slug}/media", response_class=HTMLResponse)
async def upload_media_partial(
    request: Request,
    slug: str,
    files: list[UploadFile] = File(...),
    label: str = Form("rumor"),
    caption: str = Form(""),
    db: Session = Depends(get_db_session),
):
    rumor = get_rumor_by_slug(db, slug)
    if rumor is None:
        raise HTTPException(status_code=404, detail="Rumor not found")

    new_items: list[dict] = []
    error: str | None = None
    media_label = label if label in MEDIA_IMAGE_LABELS else "rumor"

    for upload in files:
        if upload.content_type not in ALLOWED_IMAGE_MIMES:
            error = f"不支持的格式：{upload.filename} ({upload.content_type})"
            continue

        data = await upload.read()
        if len(data) > MAX_UPLOAD_BYTES:
            error = f"超出 {MAX_UPLOAD_BYTES // (1024*1024)}MB 上限：{upload.filename}"
            continue
        if not data:
            error = f"空文件：{upload.filename}"
            continue

        # Pillow 二次校验（防伪造 MIME）
        try:
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
        except (UnidentifiedImageError, Exception):
            error = f"不是有效图片：{upload.filename}"
            continue

        original = upload.filename or "image"
        stem = _safe_filename_stem(original.rsplit(".", 1)[0])
        ext = _EXT_BY_MIME.get(upload.content_type, ".bin")
        # 时间戳前缀防同名覆盖
        filename = f"{int(time.time() * 1000)}_{stem}{ext}"

        rel_path = save_image(data, slug, filename)
        new_items.append({
            "type": "image",
            "path": rel_path,
            "label": media_label,
            "caption": caption.strip(),
        })

    if new_items:
        add_media_files(db, rumor.id, new_items)
        db.commit()
        rumor = get_rumor_by_slug(db, slug)

    return _render_media_manager(request, rumor, error=error)


@router.delete("/rumors/{slug}/media", response_class=HTMLResponse)
def delete_media_partial(
    request: Request,
    slug: str,
    path: str,
    db: Session = Depends(get_db_session),
):
    rumor = get_rumor_by_slug(db, slug)
    if rumor is None:
        raise HTTPException(status_code=404, detail="Rumor not found")

    # 仅允许删除 rumor 自身 media_files 中存在的 path（防越权）
    existing = {(m or {}).get("path") for m in (rumor.media_files or [])}
    if path not in existing:
        raise HTTPException(status_code=400, detail="Path not in this rumor")

    remove_media_file(db, rumor.id, path)
    db.commit()
    rumor = get_rumor_by_slug(db, slug)
    return _render_media_manager(request, rumor)
