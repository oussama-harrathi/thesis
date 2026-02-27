# Copilot Instructions — AI-Assisted Exam Builder (Thesis MVP)

## 1) Project Goal

Build a thesis MVP called:

**AI-Assisted Exam Builder for University Courses**

The app must support two workflows (no authentication):
- **Professor Mode**: generate/review/export exams
- **Student Mode**: generate practice questions/quizzes

Questions must be generated **only from uploaded course materials** (RAG-constrained).
The system must support:

- MCQ
- True/False
- Short Answer
- Essay / Development questions

The system must also apply quality controls:
- Difficulty tagging (Easy / Medium / Hard)
- Bloom’s taxonomy tagging
- MCQ distractor validation

The system must export:
- Exam PDF
- Answer Key PDF
- LaTeX source (fallback/primary)

---

## 2) MVP Constraints (Must Follow)

### 2.1 No Authentication
Do NOT implement:
- login
- registration
- JWT
- session auth
- user roles
- auth middleware

This is a local/shared thesis MVP.

Instead, support two route namespaces:
- `/professor/*`
- `/student/*`

### 2.2 Frontend Stack (React)
Use:
- **React + TypeScript + Vite**
- **React Router**
- **TanStack Query** for API data fetching
- simple UI library allowed (MUI or shadcn/ui)

Do NOT use server-rendered Jinja pages for the main app UI.

### 2.3 Backend Stack
Use:
- Python 3.11+
- FastAPI
- SQLAlchemy 2.0
- Pydantic v2
- Alembic
- PostgreSQL + pgvector
- Redis
- Celery (or RQ) for background jobs
- PyMuPDF for PDF extraction
- Jinja2 only for **LaTeX template rendering** (export)

---

## 3) Core Functional Requirements

## 3.1 Course & Document Management
- Create/list/update courses
- Upload PDF course documents
- Store document metadata
- Process documents asynchronously:
  1. Extract text
  2. Clean text
  3. Chunk text
  4. Embed chunks
  5. Store chunks in pgvector
  6. Extract topics

## 3.2 Topic Extraction & Coverage
- Auto-detect course topics from uploaded material
- Show topic list
- Allow manual topic add/edit/delete
- Allow balanced topic distribution (auto)
- Allow professor manual topic distribution override

## 3.3 Question Generation (RAG-Only)
Generate questions only from retrieved chunks of uploaded course material.

Supported types:
- MCQ
- True/False
- Short Answer
- Essay

Every generated question must store:
- source chunk references
- source snippets
- difficulty tag
- bloom tag
- validation results
- model name + prompt version (metadata)

## 3.4 Quality Controls
Implement:
- difficulty tagging
- Bloom taxonomy tagging
- MCQ distractor validation
- grounding validation (must have source chunks)
- duplicate detection warning (embedding similarity)

## 3.5 Professor Mode
Professors can:
- define an exam blueprint (counts, difficulty mix, topic mix)
- generate batch questions
- review/edit questions
- approve/reject questions
- assemble exam
- export exam + answer key (PDF / LaTeX)

## 3.6 Student Mode
Students can:
- choose course
- choose topics (optional)
- choose question types and count
- generate a practice set
- reveal answers/explanations

No login, no personal score history in MVP.

---

## 4) Architecture Rules

## 4.1 Backend Design
Use layered architecture:
- `api/routes` = request/response only
- `services` = business logic
- `models` = SQLAlchemy ORM
- `schemas` = Pydantic
- `llm` = model providers + prompts
- `workers` = Celery tasks

Do NOT put business logic directly in FastAPI route handlers.

## 4.2 Frontend Design
Use:
- pages
- reusable components
- typed API client
- React Query hooks

Prefer small components and predictable state.

## 4.3 AI Provider Abstraction
Implement LLM provider abstraction:
- base interface
- OpenAI-compatible provider (for Groq/OpenRouter and similar APIs)
- Gemini provider (Google Gemini API / AI Studio)
- Ollama provider (optional local)
- Mock provider (for tests)

Select provider via environment variables.

Important:
- Do not hardcode OpenAI-specific behavior in the shared abstraction.
- Groq/OpenRouter should be supported through the OpenAI-compatible adapter.
- Gemini should use its own adapter because request/response format differs.

## 5) Grounding and AI Safety Rules (Critical)

## 5.1 Use Only Provided Context
All generation prompts must explicitly state:
- "Use only the provided course context."
- "If context is insufficient, return insufficient_context=true."

Do NOT allow questions to be generated from external knowledge.

## 5.2 Strict JSON Output
All LLM outputs must be strict JSON parsed with Pydantic schemas.

If parsing fails:
1. one JSON repair retry
2. if still invalid, fail that generation slot gracefully and continue

## 5.3 Traceability Required
Every generated question must have at least one source chunk and snippet.
If no source is attached, validation must fail.

---

## 6) Database Schema (MVP Minimum)

Implement these tables/models (names can match exactly):

- `courses`
- `documents`
- `chunks`
- `topics`
- `topic_chunk_map`
- `question_sets` (for student/professor generated batches)
- `questions`
- `mcq_options`
- `question_sources`
- `question_validations`
- `exam_blueprints`
- `exams`
- `exam_questions`
- `exports`
- `jobs`

Use enums for:
- document status
- question type
- difficulty
- bloom level
- question status
- job status

Use `pgvector` with `vector(384)` for chunk embeddings.

---

## 7) Required Backend Features by Module

## 7.1 Document Ingestion
Implement:
- PDF text extraction (PyMuPDF)
- text cleaning
- chunking with overlap
- embeddings (SentenceTransformers `all-MiniLM-L6-v2`)
- chunk persistence
- document processing job progress updates

## 7.2 Topic Extraction
Implement MVP topic extraction using heuristics first (headings/frequency), then optional LLM consolidation.

Store:
- topics
- topic-to-chunk relevance mappings

## 7.3 Retrieval Service
Implement pgvector similarity retrieval:
- by topic
- by query text

Return top-k chunks with relevance scores.

## 7.4 Question Generation Service
Implement generators for:
- MCQ
- True/False
- Short Answer
- Essay

Generation flow:
1. retrieve chunks
2. build grounded prompt
3. call LLM provider
4. parse/validate JSON
5. save question + options + sources
6. run validations
7. persist validation rows

## 7.5 Validation Service
Implement:
- grounding validation
- difficulty tagging
- Bloom tagging
- MCQ distractor validation
- duplicate detection (embedding similarity warning)

## 7.6 Exam Assembly Service
Implement:
- blueprint-based question batch generation
- create exam from approved questions
- reorder exam questions
- assign points

## 7.7 Export Service
Implement:
- LaTeX rendering via Jinja2 templates
- `pdflatex` compilation if available
- `.tex` fallback if not available
- export record storage

---

## 8) Required Frontend Pages (React)

## 8.1 Shared
- Home page
- Courses list
- Course detail page

## 8.2 Professor Pages
- Professor dashboard
- Course upload page
- Topics page
- Blueprint creation page
- Generation job/progress page
- Question review page
- Exam builder page
- Export page

## 8.3 Student Pages
- Student dashboard
- Practice set creation page
- Practice session page
- Optional simple results/review page

---

## 9) API Design Rules

Use JSON APIs under `/api/v1`.

Required route groups:
- courses
- documents
- topics
- generation
- questions
- blueprints
- exams
- exports
- jobs
- student practice

No auth routes.

Use:
- Pydantic request/response schemas
- clear error messages
- consistent response shapes

---

## 10) Coding Standards (Must Follow)

### Python
- Type hints required
- Use SQLAlchemy ORM + Alembic migrations
- Use service classes
- Add logging in services and workers
- Keep route handlers thin
- Handle exceptions cleanly

### React
- TypeScript everywhere
- Use React Query for server state
- Keep API calls in `src/lib/api.ts`
- Use feature-based pages/components
- Avoid giant components

### General
- Implement MVP only (do not add unrelated features)
- Write code incrementally
- Ensure each step compiles/runs before moving on
- Add TODO only if blocked

---

## 11) Project Structure (Target)

backend/
  app/
    main.py
    core/
      config.py
      database.py
      logging.py
    models/
      course.py
      document.py
      chunk.py
      topic.py
      question.py
      exam.py
      export.py
      job.py
    schemas/
      common.py
      course.py
      document.py
      topic.py
      question.py
      blueprint.py
      exam.py
      export.py
      job.py
    api/
      routes/
        health.py
        courses.py
        documents.py
        topics.py
        generation.py
        questions.py
        blueprints.py
        exams.py
        exports.py
        jobs.py
        student_practice.py
    services/
      course_service.py
      document_ingestion_service.py
      chunking_service.py
      embedding_service.py
      topic_extraction_service.py
      retrieval_service.py
      question_generation_service.py
      validation_service.py
      blueprint_service.py
      exam_assembly_service.py
      export_service.py
      practice_service.py
    llm/
      base.py
      openai_provider.py
      ollama_provider.py
      mock_provider.py
      prompts/
        topic_extraction.py
        mcq_generation.py
        tf_generation.py
        short_answer_generation.py
        essay_generation.py
        difficulty_classifier.py
        bloom_classifier.py
        distractor_validator.py
    workers/
      celery_app.py
      tasks.py
    templates/
      latex/
        exam_template.tex.j2
        answer_key_template.tex.j2
    utils/
      pdf.py
      text_cleaning.py
      json_retry.py
      latex.py
  alembic/
  tests/
  requirements.txt
  Dockerfile

frontend/
  src/
    main.tsx
    App.tsx
    lib/
      api.ts
      queryClient.ts
    types/
      api.ts
    pages/
      HomePage.tsx
      CoursesPage.tsx
      CourseDetailPage.tsx
      professor/
      student/
    components/
    hooks/
  package.json
  vite.config.ts

docker-compose.yml

---

## 12) Implementation Order (Follow This)

Always build in this order:

1. Foundations
   - backend scaffold
   - frontend scaffold
   - docker compose
   - DB connection
2. DB models + Alembic
3. Course CRUD + document upload
4. Document processing pipeline (PDF -> chunks -> embeddings)
5. Topic extraction + topics UI
6. LLM provider abstraction + retrieval
7. Question generation (MCQ + True/False first)
8. Validations (difficulty, bloom, distractors)
9. Professor blueprint + review + exam assembly
10. Student practice mode
11. Export (LaTeX + PDF)
12. Tests + polish

Do NOT skip ahead.

---

## 13) Testing Requirements

Implement tests for:
- text cleaning
- chunking
- distractor validation
- blueprint allocation
- LaTeX rendering fallback
- question generation using MockProvider

Do not depend on live LLM APIs in tests.

---

## 14) Acceptance Criteria (MVP Complete)

The MVP is complete when:

1. A course can be created.
2. PDFs can be uploaded and processed.
3. Topics are extracted and editable.
4. Professor can generate question batches.
5. Student can generate practice sets.
6. All 4 question types work.
7. Each question has source snippets + validation metadata.
8. Professor can review/approve questions.
9. Professor can assemble an exam.
10. Exam + answer key export works (PDF or .tex fallback).
11. App runs locally with Docker Compose.

---

## 15) Copilot Behavior Rules

When generating code for this repo, always:
1. Follow this file (`.github/copilot-instructions.md`)
2. Prefer small, incremental changes
3. Keep logic modular
4. Avoid adding auth
5. Avoid inventing extra features not in MVP
6. Keep AI generation grounded and traceable
7. Use service layer and typed schemas