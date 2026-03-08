from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
from src.db.models import RumorStatus


# ─── Rumor Schemas ───

class RumorCreate(BaseModel):
    title: str
    slug: str
    summary: str | None = None
    rumor_content: str | None = None
    truth_content: str | None = None
    status: RumorStatus = RumorStatus.DUBIOUS
    tags: list[str] | None = None
    media_files: list[dict] | None = None
    source_urls: list[str] | None = None
    is_published: bool = False


class RumorUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    rumor_content: str | None = None
    truth_content: str | None = None
    status: RumorStatus | None = None
    tags: list[str] | None = None
    media_files: list[dict] | None = None
    source_urls: list[str] | None = None
    is_published: bool | None = None


class RumorSampleIn(BaseModel):
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


class RumorOut(BaseModel):
    id: UUID
    title: str
    slug: str
    summary: str | None
    rumor_content: str | None
    truth_content: str | None
    status: RumorStatus
    tags: list[str] | None
    media_files: list | None
    source_urls: list | None
    view_count: int
    is_published: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── AnalysisResult Schemas ───

class AnalysisResultCreate(BaseModel):
    rumor_id: UUID
    summary: str | None = None
    truthfulness_score: float = Field(ge=0.0, le=1.0)
    evidence: str | None = None
    model_name: str | None = None


class AnalysisResultOut(BaseModel):
    id: int
    rumor_id: UUID
    summary: str | None
    truthfulness_score: float
    evidence: str | None
    model_name: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
