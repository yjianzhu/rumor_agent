import enum
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float, Enum
from sqlalchemy.orm import relationship, deferred
from sqlalchemy.sql import func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from pgvector.sqlalchemy import Vector
from src.db.base import Base

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
    slug = Column(String(255), unique=True) # URL friendly slug

    # 2. Content
    summary = Column(Text)
    rumor_content = Column(Text)
    truth_content = Column(Text)

    # 3. Classification & Attributes
    status = Column(Enum(RumorStatus), default=RumorStatus.DUBIOUS)
    tags = Column(ARRAY(Text)) # List of tags

    # 4. Media & Sources (JSONB)
    media_files = Column(JSONB, server_default=text("'[]'::jsonb"))
    source_urls = Column(JSONB, server_default=text("'[]'::jsonb"))

    # 4b. Embedding for semantic dedup (deferred: not loaded in normal queries)
    embedding = deferred(Column(Vector(1536), nullable=True))

    # 5. Stats & Meta
    view_count = Column(Integer, default=0)
    is_published = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    analysis = relationship("AnalysisResult", back_populates="rumor", uselist=False)

class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    # Changed foreign key to UUID to match Rumor's ID
    rumor_id = Column(UUID(as_uuid=True), ForeignKey("rumors.id"), unique=True)
    
    summary = Column(Text)
    truthfulness_score = Column(Float) # 0.0 to 1.0
    evidence = Column(Text) 
    model_name = Column(String(100))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    rumor = relationship("Rumor", back_populates="analysis")
