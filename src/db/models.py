import enum
from sqlalchemy import Column, Index, Integer, String, Text, DateTime, ForeignKey, Boolean, Float, Enum
from sqlalchemy.orm import relationship, deferred
from sqlalchemy.sql import func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from pgvector.sqlalchemy import Vector
from src.db.base import Base
from src.config import settings


class RumorStatus(str, enum.Enum):
    FAKE = "FAKE"
    TRUE = "TRUE"
    DUBIOUS = "DUBIOUS"
    OUTDATED = "OUTDATED"


class Rumor(Base):
    __tablename__ = "rumors"

    # 1. Basic Info
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    title = Column(Text, nullable=False)
    slug = Column(String(255), unique=True)  # URL friendly slug

    # 2. Content
    summary = Column(Text)
    rumor_content = Column(Text)
    truth_content = Column(Text)

    # 3. Classification & Attributes
    status = Column(Enum(RumorStatus), default=RumorStatus.DUBIOUS)
    tags = Column(ARRAY(Text))  # List of tags

    # 4. Media & Sources
    media_files = Column(JSONB, server_default=text("'[]'::jsonb"))
    # source_urls uses ARRAY(Text) to match tags; JSONB kept only for structured media_files
    source_urls = Column(ARRAY(Text), server_default=text("'{}'::text[]"))

    # 4b. Embedding for semantic dedup (deferred: not loaded in normal queries)
    # Dimension is driven by settings.EMBEDDING_DIM to stay in sync with the model
    embedding = deferred(Column(Vector(settings.EMBEDDING_DIM), nullable=True))

    # 5. Stats & Meta
    view_count = Column(Integer, default=0)
    # Number of times this rumor absorbed a duplicate candidate (source/tag union)
    merge_count = Column(Integer, nullable=False, server_default=text("0"))
    is_published = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # onupdate handles ORM-level updates; a DB trigger covers raw-SQL updates (see init_db.py)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    analysis = relationship("AnalysisResult", back_populates="rumor", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_rumors_created_at", created_at.desc()),
        Index("ix_rumors_status", status),
        Index("ix_rumors_is_published", is_published),
        Index("ix_rumors_tags", tags, postgresql_using="gin"),
    )


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    rumor_id = Column(UUID(as_uuid=True), ForeignKey("rumors.id"), unique=True)

    summary = Column(Text)
    truthfulness_score = Column(Float)  # 0.0 to 1.0
    evidence = Column(Text)
    model_name = Column(String(100))

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    rumor = relationship("Rumor", back_populates="analysis")
