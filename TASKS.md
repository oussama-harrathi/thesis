# TASKS.md — Thesis MVP Tracker


## Phase 1 — Foundations
- [x] Create backend FastAPI scaffold
- [x] Add `/api/v1/health`
- [x] Create frontend React + Vite + TS scaffold
- [x] Add React Router basic pages
- [x] Create docker-compose for postgres(pgvector) + redis
- [x] Test backend DB connection endpoint

## Phase 2 — Database + Alembic
- [x] Set up SQLAlchemy 2.0 base/session
- [x] Set up Alembic
- [x] Create core models (courses, documents)
- [x] Create chunk/topic models
- [x] Create question models
- [x] Create jobs model
- [x] Run initial migration

## Phase 3 — Course + Document Upload
- [x] Course CRUD API
- [x] Course pages in React
- [x] PDF upload endpoint
- [x] Save file locally
- [x] Create Job row on upload

## Phase 4 — Document Processing Pipeline
- [x] Celery setup
- [x] PDF extraction utility (PyMuPDF)
- [x] Text cleaning utility
- [x] Chunking service
- [x] Embedding service (MiniLM)
- [x] Save chunks to DB
- [x] Update job progress/status

## Phase 5 — Topics
- [x] Topic extraction service (heuristic MVP)
- [x] Save topics + topic_chunk_map
- [x] Topics API
- [x] Topics React page (view/add/edit/delete)

## Phase 6 — LLM + Retrieval
- [x] LLM provider base interface
- [x] OpenAI-compatible provider (for Groq/OpenRouter)
- [x] Gemini provider
- [x] Ollama provider (optional local)
- [x] Mock provider
- [x] Prompt files structure
- [x] pgvector retrieval service

## Phase 7 — Question Generation (MCQ + TF first)
- [x] Pydantic schemas for LLM outputs
- [x] MCQ generator
- [x] True/False generator
- [x] Save question_sources
- [x] Generation API endpoints

## Phase 8 — Quality Controls
- [x] Grounding validation
- [x] MCQ distractor validation
- [x] Difficulty tagging
- [x] Bloom tagging
- [x] Store validation rows
- [x] Wire all validators into generation flow

## Phase 9 — Professor Exam Workflow
- [x] Blueprint model + API
- [x] Blueprint generation job
- [x] Question review page
- [x] Approve/reject/edit flow
- [x] Exam assembly API + UI

## Phase 10 — Student Practice Workflow
- [x] Practice set API
- [x] Practice generation flow
- [x] Practice UI (answer reveal/explanations)

## Phase 11 — Export
- [x] LaTeX templates
- [x] Export service
- [x] PDF compile with fallback
- [x] Export download endpoint/UI

## Phase 12 — Testing + Polish
- [x] Unit tests for core services
- [x] Integration tests (mock provider)
- [ ] Demo test run (end-to-end)
- [ ] Final cleanup