# AI-Assisted Exam Builder

AI-Assisted Exam Builder is a full-stack platform for creating course-grounded exams from uploaded PDF material. Professors can upload course documents, extract and organize their content, generate candidate questions with large language models, review the results, assemble exams, and export exam files with answer keys. The application also includes a student practice mode that generates practice questions from the same course material.

## Core Features

- Course and document management
- PDF text extraction, cleaning, chunking, and storage
- Embedding-based semantic retrieval with PostgreSQL and pgvector
- Topic extraction and topic-to-chunk mapping
- Blueprint-driven exam generation
- Multiple question types: Multiple Choice, True/False, Short Answer, and Essay
- Retrieval-grounded LLM prompts with source tracking
- Validation for grounding, difficulty, Bloom level, correctness, distractor quality, and duplication
- Professor review workflow for approving, rejecting, editing, and replacing generated questions
- Exam assembly with ordering and point assignment
- LaTeX and PDF export for exams and answer keys
- Student practice sessions based on selected courses, topics, question types, and difficulty

## User Workflows

### Professor

1. Create a course.
2. Upload one or more PDF documents.
3. Let the backend process the documents in the background.
4. Review extracted topics.
5. Create an exam blueprint with question counts, difficulty mix, topic coverage, points, and duration.
6. Generate candidate questions from the blueprint.
7. Review, edit, approve, reject, or replace generated questions.
8. Assemble an exam from approved questions.
9. Reorder questions and adjust point values.
10. Export the exam and answer key as LaTeX or PDF.

### Student

1. Select a course.
2. Optionally select topics.
3. Choose question types, count, and difficulty.
4. Generate a practice set.
5. Answer questions in the practice interface.

## Architecture

```text
Frontend (React + Vite)
        |
        v
Backend API (FastAPI)
        |
        +--> PostgreSQL + pgvector
        |
        +--> Redis
        |
        +--> Celery Worker
        |        |
        |        +--> PDF extraction
        |        +--> chunking and embeddings
        |        +--> topic extraction
        |        +--> question generation
        |        +--> validation and persistence
        |
        +--> Export service
                 |
                 +--> Jinja2 templates
                 +--> LaTeX output
                 +--> optional PDF compilation
```

The backend exposes versioned API routes under `/api/v1`. Long-running work, such as document processing and question generation, runs through Celery jobs and is tracked in the database so the frontend can display progress.

## Technology Stack

### Backend

- FastAPI
- SQLAlchemy 2.x
- PostgreSQL
- pgvector
- Redis
- Celery
- PyMuPDF
- sentence-transformers with `all-MiniLM-L6-v2`
- Jinja2
- LaTeX tooling through TeX Live or MiKTeX

### Frontend

- React 18
- TypeScript
- Vite
- React Router
- TanStack React Query

### LLM Providers

The LLM layer uses a provider abstraction so generation can run through different backends without changing the business logic. Supported provider options include:

- `openai_compatible`
- `cerebras`
- `gemini`
- `ollama`
- `mock`

Fallback providers can be configured for resilience when the primary provider is unavailable.

## Main Backend Components

- `document_ingestion_service.py`: validates uploads, stores files, creates document records, and starts processing jobs.
- `chunking_service.py`: splits cleaned document text into overlapping chunks with page and offset metadata.
- `embedding_service.py`: creates embeddings for chunks and generated questions.
- `topic_extraction_service.py`: extracts topic structures and maps topics to relevant chunks.
- `retrieval_service.py`: retrieves relevant chunks for generation with semantic search and filtering.
- `question_generation_service.py`: generates and persists questions, answers, sources, and validation results.
- `validation_service.py`: runs quality checks on generated questions.
- `diversity_service.py`: reduces duplicate and near-duplicate question generation.
- `blueprint_service.py`: stores blueprint configuration and expands it into generation slots.
- `exam_assembly_service.py`: builds exams from approved questions.
- `export_service.py`: renders exams and answer keys to LaTeX and optionally compiles PDFs.
- `practice_service.py`: creates student practice sets.

## Data Model

The application stores course content, generated questions, validation results, and exported artifacts as explicit database entities.

Core entities include:

- `Course`
- `Document`
- `Chunk`
- `Topic`
- `TopicChunkMap`
- `QuestionSet`
- `Question`
- `McqOption`
- `QuestionSource`
- `QuestionValidation`
- `ExamBlueprint`
- `BlueprintQuestion`
- `Exam`
- `ExamQuestion`
- `Export`
- `Job`

Generated questions keep links to their supporting chunks, making each question traceable back to the uploaded source material.

## Repository Structure

```text
.
|-- Backend/
|   |-- app/
|   |   |-- api/routes/
|   |   |-- core/
|   |   |-- llm/
|   |   |-- models/
|   |   |-- schemas/
|   |   |-- services/
|   |   |-- templates/latex/
|   |   |-- utils/
|   |   `-- workers/
|   |-- alembic/
|   |-- tests/
|   |-- requirements.txt
|   `-- Dockerfile
|-- Frontend/
|   |-- src/
|   |   |-- components/
|   |   |-- hooks/
|   |   |-- lib/
|   |   |-- pages/
|   |   `-- types/
|   |-- package.json
|   `-- Dockerfile
|-- docker-compose.yml
|-- .env.example
`-- start
```

## Local Development

### Docker

From the project root:

```powershell
docker compose up -d
```

This starts:

- PostgreSQL with pgvector
- Redis
- FastAPI backend
- Celery worker
- frontend

Default ports:

- backend: `8001`
- frontend: `80`
- PostgreSQL: `5433`
- Redis: `6379`

### Backend

```powershell
cd Backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### Worker

```powershell
cd Backend
python -m celery -A app.workers.celery_app worker --loglevel=info --pool=solo --without-gossip --without-mingle
```

### Frontend

```powershell
cd Frontend
npm install
npm run dev
```

## Environment Variables

Important backend variables:

- `DATABASE_URL`
- `DATABASE_URL_SYNC`
- `REDIS_URL`
- `LLM_PROVIDER`
- `LLM_FALLBACK_PROVIDER`
- `LLM_SECOND_FALLBACK_PROVIDER`
- `OPENAI_COMPATIBLE_API_KEY`
- `OPENAI_COMPATIBLE_BASE_URL`
- `OPENAI_COMPATIBLE_MODEL`
- `CEREBRAS_API_KEY`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `OLLAMA_BASE_URL`
- `CORS_ORIGINS`
- `UPLOAD_DIR`
- `EXPORT_DIR`

Frontend:

- `VITE_API_BASE_URL`

The frontend expects `VITE_API_BASE_URL` to point to the backend base URL, such as `http://localhost:8001`. The app appends `/api/v1` internally.

## Current Limitations

- PDF extraction is text-first and does not perform OCR.
- Image-heavy slides, diagrams, and formulas embedded as images may not be fully represented.
- Question quality depends on the quality and specificity of the uploaded material.
- Student practice currently focuses mainly on Multiple Choice and True/False questions.
- PDF export depends on an available LaTeX installation when running outside Docker.
- Some validation checks are heuristic and may require professor review for final judgment.
