# TASKS.md — Thesis MVP Tracker

## Current Focus
- Phase: 6 — LLM + Retrieval (next)
- Phase 5 fully complete

---

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
- [ ] LLM provider base interface
- [ ] OpenAI-compatible provider
- [ ] Ollama provider
- [ ] Mock provider
- [ ] Prompt files structure
- [ ] pgvector retrieval service

## Phase 7 — Question Generation (MCQ + TF first)
- [ ] Pydantic schemas for LLM outputs
- [ ] MCQ generator
- [ ] True/False generator
- [ ] Save question_sources
- [ ] Generation API endpoints

## Phase 8 — Quality Controls
- [ ] Grounding validation
- [ ] MCQ distractor validation
- [ ] Difficulty tagging
- [ ] Bloom tagging
- [ ] Store validation rows

## Phase 9 — Professor Exam Workflow
- [ ] Blueprint model + API
- [ ] Blueprint generation job
- [ ] Question review page
- [ ] Approve/reject/edit flow
- [ ] Exam assembly API + UI

## Phase 10 — Student Practice Workflow
- [ ] Practice set API
- [ ] Practice generation flow
- [ ] Practice UI (answer reveal/explanations)

## Phase 11 — Export
- [ ] LaTeX templates
- [ ] Export service
- [ ] PDF compile with fallback
- [ ] Export download endpoint/UI

## Phase 12 — Testing + Polish
- [ ] Unit tests for core services
- [ ] Integration tests (mock provider)
- [ ] Demo test run (end-to-end)
- [ ] Final cleanup