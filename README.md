# Rumor Agent - Project Design & Plan

## 1. Project Overview
**Rumor Agent** is an intelligent system designed to detect, track, analyze, and verify network rumors. It leverages LLMs (Large Language Models) to assess the truthfulness of claims, aggregate evidence, and provide automated debunks or verifications.

## 2. Architecture Design
The system consists of the following core components:

*   **Ingestion Layer**: Collects rumors from various sources (social media, news, user submissions).
*   **Data Layer**: PostgreSQL database storing rumor content, media references, and analysis results (using SQLAlchemy).
*   **Analysis Core**: AI Agent responsible for:
    *   Claim extraction.
    *   Fact-checking against trusted sources.
    *   Sentiment and classification analysis.
*   **API / Interface**: Interfaces for users to query rumors or view analysis results.

## 3. Data Model (Current Status)
The database schema is built using SQLAlchemy ORM.

### Tables
1.  **`rumors`**
    *   **Core**: `id` (UUID), `title`, `slug`.
    *   **Content**: `summary`, `rumor_content`, `truth_content`.
    *   **Status**: `Enum` (FAKE, TRUE, DUBIOUS, OUTDATED).
    *   **Metadata**: `tags`, `view_count`, `is_published`, `created_at`.
    *   **Sources**: `media_files` (JSON), `source_urls` (JSON).

2.  **`analysis_results`**
    *   **Relation**: Linked to `rumors` (One-to-One).
    *   **Analysis**: `truthfulness_score` (0.0-1.0), `evidence` (text), `summary`.
    *   **Meta**: `model_name` used for analysis.

## 4. Roadmap & Implementation Plan

### Phase 1: Foundation (Current)
- [x] Set up Python environment.
- [x] Define database models (Rumor, AnalysisResult).
- [x] Create database initialization script (`init_db.py`).
- [x] Implement basic CRUD operations for Rumors.

### Phase 2: Core Analysis Logic
- [ ] Integrate LLM client (e.g., OpenAI/Gemini).
- [ ] Implement `Analyzer` module to take a rumor and output an `AnalysisResult`.
- [ ] Develop evidence gathering module (Web Search integration).

### Phase 3: Ingestion & Pipeline
- [ ] Create scrapers or API connectors for source input.
- [ ] Build a task queue (if needed) for processing rumors asynchronously.

### Phase 4: API & Frontend
- [ ] Build a REST/GraphQL API (FastAPI recommended).
- [ ] Develop a user-facing dashboard to view rumors and analysis.

## 5. Setup & Usage

### Prerequisites
*   Python 3.10+
*   PostgreSQL with `uuid-ossp` extension enabled.

### Installation
1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Environment Setup**:
    Configure your `.env` file with `DATABASE_URL` and model API keys.
    *(See `src/config.py`)*

3.  **Initialize Database**:
    ```bash
    python init_db.py
    ```
    This script will enable necessary extensions and create all tables defined in `src/db/models.py`.

## 6. Directory Structure
```
rumor_agent/
├── init_db.py          # Database initialization script
├── requirements.txt    # Project dependencies
└── src/
    ├── config.py       # Configuration management
    ├── main.py         # Entry point (TBD)
    └── db/
        ├── base.py     # SQLAlchemy Base and Engine
        ├── models.py   # Database models
        ├── schemas.py  # Pydantic validation schemas
        └── crud.py     # CRUD operations
```
