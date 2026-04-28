from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field
from src.db.models import RumorStatus


class MediaItem(BaseModel):
    type: Literal["image", "video"]
    path: str          # 图片: 相对路径 "media/<slug>/xxx.jpg"；视频: 完整 URL
    label: str = ""    # 用途标签，如 "rumor", "debunk", "source"
    caption: str = ""  # 可选说明


# ─── Rumor Schemas ───

class RumorCreate(BaseModel):
    title: str
    slug: str
    summary: str | None = None
    rumor_content: str | None = None
    truth_content: str | None = None
    status: RumorStatus = RumorStatus.DUBIOUS
    tags: list[str] | None = None
    media_files: list[MediaItem] | None = None
    source_urls: list[str] | None = None
    is_published: bool = False


class RumorUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    rumor_content: str | None = None
    truth_content: str | None = None
    status: RumorStatus | None = None
    tags: list[str] | None = None
    media_files: list[MediaItem] | None = None
    source_urls: list[str] | None = None
    is_published: bool | None = None


class RumorDirectIn(BaseModel):
    """Schema for direct JSONL import — no LLM needed.

    ``slug`` is optional: if omitted it is auto-generated from ``title``.
    Include ``truthfulness_score`` (and optionally ``analysis_summary`` /
    ``evidence`` / ``model_name``) to also write an ``analysis_results`` row.
    """
    title: str
    slug: str | None = None
    summary: str | None = None
    rumor_content: str | None = None
    truth_content: str | None = None
    status: RumorStatus = RumorStatus.DUBIOUS
    tags: list[str] | None = None
    media_files: list[MediaItem] | None = None
    source_urls: list[str] | None = None
    is_published: bool = False
    # optional inline analysis
    analysis_summary: str | None = None
    truthfulness_score: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: str | None = None
    model_name: str | None = None


class RumorOut(BaseModel):
    id: UUID
    title: str
    slug: str
    summary: str | None
    rumor_content: str | None
    truth_content: str | None
    status: RumorStatus
    tags: list[str] | None
    media_files: list[MediaItem] | None
    source_urls: list[str] | None
    view_count: int
    is_published: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── Internal: used by --import-md (LLM path) ───

class _RumorSampleIn(BaseModel):
    """Internal-only: wraps raw markdown text for LLM analysis."""
    raw_text: str = Field(min_length=1)
    title: str | None = None
    source_urls: list[str] | None = None
    tags: list[str] | None = None
    is_published: bool = False


class StructuredRumorAnalysis(BaseModel):
    title: str = Field(min_length=1)
    summary: str | None = None
    rumor_content: str = Field(min_length=1)
    truth_content: str | None = None
    status: RumorStatus = RumorStatus.DUBIOUS
    tags: list[str] | None = None
    source_urls: list[str] | None = None
    analysis_summary: str | None = None
    truthfulness_score: float = Field(ge=0.0, le=1.0)
    evidence: str | None = None


# ─── AnalysisResult Schemas ───

class AnalysisResultCreate(BaseModel):
    rumor_id: UUID
    summary: str | None = None
    truthfulness_score: float = Field(ge=0.0, le=1.0)
    evidence: str | None = None
    model_name: str | None = None


class AnalysisResultOut(BaseModel):
    id: UUID
    rumor_id: UUID
    summary: str | None
    truthfulness_score: float
    evidence: str | None
    model_name: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Composite / API response schemas ───

class RumorDetailOut(RumorOut):
    analysis: AnalysisResultOut | None = None


class StatsOut(BaseModel):
    total: int
    by_status: dict[str, int]
    published: int
    recent_7d: int


class PaginatedRumorOut(BaseModel):
    items: list[RumorOut]
    total: int
    offset: int
    limit: int
