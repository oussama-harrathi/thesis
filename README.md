# AI-Assisted Exam Builder

## 1. Project Summary

This project is a full-stack AI-assisted assessment generation platform designed for university-level teaching. It allows a professor to upload course PDFs, extract and organize course content, generate grounded exam questions with large language models, review and curate those questions, assemble a final exam, and export the result as LaTeX or PDF. It also includes a student practice mode that generates on-demand practice sets from the same course material.

The system is not just a "question generator". It is a complete workflow with:

- document ingestion and background processing
- text extraction, cleaning, chunking, embedding, and semantic retrieval
- topic extraction and topic-chunk mapping
- blueprint-driven exam design
- LLM-based question generation with multiple question types
- validation, grounding, difficulty control, and diversity safeguards
- professor review and approval
- exam assembly and export
- student self-practice

The overall design is human-in-the-loop. AI generates candidate content, but the professor remains the final authority over what enters the exam.

## 2. Thesis-Relevant Problem Statement

Creating high-quality exams from large amounts of course material is time-consuming. A professor must:

- identify the important parts of the material
- cover multiple topics and difficulty levels
- avoid duplication and trivial questions
- ensure that questions are grounded in the course content
- assemble and format the final exam for actual use

This project addresses that problem by combining retrieval-augmented generation (RAG), background processing, structured validation, and human review into one educational workflow.

In thesis terms, the project can be described as:

- a domain-specific RAG system for educational assessment generation
- a human-supervised question generation pipeline
- a software engineering solution for traceable and controllable AI-generated exams

## 3. Main Goals

- Turn uploaded course PDFs into a structured knowledge base.
- Generate exam questions that are traceable to source material.
- Support multiple question types: MCQ, True/False, Short Answer, and Essay.
- Respect professor-defined blueprint requirements such as counts, topics, and difficulty mix.
- Reduce low-quality outputs through retrieval constraints and validation gates.
- Keep the professor in control through review, approval, rejection, editing, and replacement.
- Export exams in a form suitable for real academic use.

## 4. Main Users and Workflows

### Professor Workflow

1. Create a course.
2. Upload one or more PDF documents.
3. Let the backend process the documents in the background.
4. Inspect extracted topics.
5. Create an exam blueprint:
   - question counts per type
   - difficulty mix
   - optional Bloom mix
   - automatic or manual topic mix
   - total points and duration
6. Start blueprint generation.
7. Review generated questions:
   - approve
   - reject
   - edit
   - replace
8. Assemble an exam from approved questions.
9. Reorder questions and set points.
10. Export the exam and answer key to LaTeX or PDF.

### Student Workflow

1. Choose a course.
2. Optionally choose topics.
3. Choose practice question types and count.
4. Generate a practice set from course material.
5. Answer questions in the student practice interface.

## 5. High-Level Architecture

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
                 |
                 +--> PDF extraction
                 +--> chunking + embeddings
                 +--> topic extraction
                 +--> blueprint-driven question generation
                 +--> validation + persistence
        |
        +--> Export service
                 |
                 +--> Jinja2 -> LaTeX
                 +--> pdflatex -> PDF
```

## 6. Technology Stack

### Backend

- FastAPI
- SQLAlchemy 2.x
- PostgreSQL
- pgvector
- Redis
- Celery
- PyMuPDF
- sentence-transformers (`all-MiniLM-L6-v2`)
- Jinja2
- MiKTeX on Windows or TeX Live in Docker for PDF export

### Frontend

- React 18
- TypeScript
- Vite
- React Router
- TanStack React Query

### AI / LLM Layer

- provider abstraction with pluggable backends
- currently supported providers:
  - `openai_compatible`
  - `cerebras`
  - `gemini`
  - `ollama`
  - `mock`
- automatic fallback chaining between providers

## 7. Repository Structure

```text
Miskolc Thesis/
├── Backend/
│   ├── app/
│   │   ├── api/routes/
│   │   ├── core/
│   │   ├── llm/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── templates/latex/
│   │   ├── utils/
│   │   └── workers/
│   ├── alembic/
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── Frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── lib/
│   │   ├── pages/
│   │   └── types/
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
└── start
```

## 8. Backend Architecture

### 8.1 API Layer

The backend entry point is `Backend/app/main.py`. It exposes route groups for:

- health
- courses
- documents
- topics
- generation
- blueprints
- jobs
- questions
- exams
- student practice
- exports

The API is versioned under `/api/v1`.

### 8.2 Background Jobs

Long-running tasks are not executed in the request thread. They are moved to Celery jobs and tracked in the `jobs` table.

Main job types:

- `document_processing`
- `question_generation`

Each job stores:

- status (`pending`, `running`, `completed`, `failed`)
- progress (0-100)
- human-readable message
- optional error/summary payload

### 8.3 Core Service Layer

The service layer contains most of the business logic:

- `document_ingestion_service.py`
  - validates upload
  - stores file
  - creates document row
  - creates processing job

- `chunking_service.py`
  - turns cleaned text into overlapping chunks
  - preserves character offsets and approximate page metadata

- `embedding_service.py`
  - computes chunk and question embeddings
  - lazy-loads `all-MiniLM-L6-v2`

- `topic_extraction_service.py`
  - extracts topics from TOC first if possible
  - falls back to heuristic heading and n-gram extraction
  - builds topic hierarchy and topic-chunk relevance mapping

- `retrieval_service.py`
  - performs semantic retrieval with pgvector
  - supports query-based and topic-based retrieval
  - filters boilerplate/admin chunks
  - supports chunk exclusion and penalization for diversity

- `question_generation_service.py`
  - generates MCQ, True/False, Short Answer, and Essay questions
  - persists question rows, options, sources, and validations

- `validation_service.py`
  - grounding checks
  - distractor checks
  - difficulty and Bloom tagging
  - triviality checks
  - correctness verification

- `diversity_service.py`
  - fingerprinting
  - recent-question deduplication
  - blacklist memory
  - historical chunk penalization

- `blueprint_service.py`
  - stores blueprint configuration
  - expands blueprint config into concrete generation slots
  - creates generation jobs and question sets

- `exam_assembly_service.py`
  - assembles approved questions into an exam
  - manages order and points

- `export_service.py`
  - renders exam and answer key to LaTeX
  - compiles PDF through `pdflatex` when available
  - falls back to `.tex` if compilation is unavailable or fails

- `practice_service.py`
  - creates student practice sets
  - currently focused on MCQ and True/False practice generation

## 9. Frontend Architecture

The frontend is a React + TypeScript single-page application.

### Main Pages

- `/`
  - home page with professor and student entry points

- `/courses`
  - course listing and management

- `/courses/:courseId`
  - course detail page

- `/courses/:courseId/topics`
  - topic management and inspection

- `/courses/:courseId/blueprints/new`
  - blueprint creation

- `/courses/:courseId/generation/:jobId`
  - live generation progress view

- `/courses/:courseId/questions`
  - question review page

- `/courses/:courseId/exam-builder`
  - exam assembly page

- `/exams/:examId/export`
  - exam export page

- `/student/practice/new`
  - student practice setup

- `/student/practice/:questionSetId`
  - student practice session page

### Frontend Design Pattern

- Components do not call `fetch` directly.
- API calls go through typed helpers in `Frontend/src/lib/api.ts`.
- React Query hooks manage fetching, caching, and invalidation.
- TypeScript interfaces mirror backend response models.

## 10. Data Model

The project data model is centered on traceable academic content generation.

### Core Entities

- `Course`
  - top-level container
  - stores `name`, `description`, and cached `detected_subject`

- `Document`
  - uploaded PDF
  - stores file metadata and processing status

- `Chunk`
  - extracted text fragment
  - stores content, chunk index, offsets, page range, embedding, and chunk type

- `Topic`
  - extracted or manual concept/topic
  - can be hierarchical (`parent_topic_id`)
  - includes `source`, `level`, and `coverage_score`

- `TopicChunkMap`
  - many-to-many mapping between topics and chunks
  - stores relevance scores

- `QuestionSet`
  - a batch of questions
  - used for both professor generation and student practice

- `Question`
  - main question record
  - stores body, type, correct answer, explanation, requested difficulty, Bloom level, status, prompt metadata, fingerprint, and embedding

- `McqOption`
  - options A-D for MCQ questions

- `QuestionSource`
  - traceability link between a question and one of its supporting chunks

- `QuestionValidation`
  - result of one validation check

- `ExamBlueprint`
  - professor-defined recipe for exam generation

- `BlueprintQuestion`
  - mapping between a blueprint and generated questions

- `Exam`
  - assembled exam

- `ExamQuestion`
  - ordered slot within an exam
  - stores position and optional points

- `Export`
  - output artifact for exam or answer key
  - PDF or LaTeX

- `Job`
  - background processing job

### Important Modeling Decision

The system stores source chunks and validation metadata explicitly. This is a major architectural choice because it makes generated questions auditable instead of opaque.

## 11. End-to-End Content Pipeline

### 11.1 Document Ingestion

When a professor uploads a PDF:

1. The backend validates that it is a PDF.
2. A SHA-256 checksum is computed.
3. The file is written to `data/uploads`.
4. A `Document` row is created.
5. A `Job` row is created.
6. Celery processes the document asynchronously.

### 11.2 PDF Extraction

The worker uses PyMuPDF to:

- read the PDF page by page
- extract raw text from each page
- preserve page order and character offsets

Important limitation:

- image-only or diagram-heavy PDFs are not fully captured because the pipeline is text-first and does not perform OCR.

### 11.3 Text Cleaning

The raw PDF text is normalized before chunking. This reduces extraction noise and prepares the material for semantic search.

### 11.4 Chunking

The chunking strategy is intentionally simple and deterministic:

- sentence and paragraph aware when possible
- character-based windows
- overlap between consecutive chunks
- page range metadata preserved approximately

Default configuration in the backend:

- chunk size: `1500`
- overlap: `200`

### 11.5 Chunk Classification

Each chunk is classified by educational role. Retrieval can hard-filter out chunk types that should never be used to generate questions, such as:

- administrative assessment text
- references / boilerplate

This avoids contaminating prompts with irrelevant material.

### 11.6 Embeddings

Each chunk is embedded using `all-MiniLM-L6-v2` and stored in PostgreSQL via pgvector. This enables semantic retrieval by cosine similarity.

## 12. Topic Extraction

Topic extraction is not purely heuristic. It follows a TOC-first strategy:

1. Try to extract the PDF's built-in outline/bookmarks.
2. If that fails, try heuristic TOC page scanning.
3. If that still fails, use heading detection and n-gram heuristics.

This produces:

- topic names
- hierarchy levels such as chapter / section / subsection
- parent-child topic links
- topic coverage scores
- topic-chunk mappings

This is important because it gives the professor a structured representation of the course before question generation starts.

## 13. Course Subject Detection

The system also tries to detect the overall subject of the course by sampling chunks and asking an LLM for a concise subject label, for example:

- "Neural Networks and Machine Learning"
- not merely "Computer Science"

The result is cached in `courses.detected_subject` and is later used to anchor retrieval in auto-topic mode.

## 14. Blueprint System

A blueprint describes the target exam before generation starts.

### Blueprint Configuration Includes

- question counts per type
- difficulty mix (`easy`, `medium`, `hard`)
- optional Bloom mix
- topic mix:
  - `auto`
  - `manual`
- total points
- duration

### Blueprint Expansion

The blueprint is expanded into many one-question generation slots. This is important because it lets the worker:

- control retries per slot
- vary retrieval per slot
- track success/failure at slot level
- keep detailed job progress

### Difficulty Distribution Logic

Difficulty distribution is allocated globally across the whole blueprint, then paired with type/topic units. This avoids the small-count rounding problem where easy questions disappear when each question type is rounded separately.

## 15. Question Generation Pipeline

This is the most important part of the system.

### Supported Question Types

- Multiple Choice
- True/False
- Short Answer
- Essay

### Basic Flow Per Question Slot

1. Build a retrieval query seed from:
   - course subject
   - topic
   - question type
   - target difficulty
2. Retrieve chunks from the vector store.
3. Build a grounded prompt that includes context.
4. Call the configured LLM provider.
5. Parse structured JSON output.
6. Apply quality gates and validation.
7. Persist the question, options, sources, and validation records.

## 16. Retrieval and Grounding Rules

The generator does not call the LLM blindly. It first enforces context requirements.

### Minimum Context by Requested Difficulty

- easy: minimum 1 chunk
- medium: minimum 2 chunks
- hard: minimum 3 chunks

If the system does not have enough usable chunks:

- it broadens retrieval first
- it attempts rescue retrieval with alternative query angles
- it avoids generating weak, under-grounded content when possible

### Retrieval Diversity

To minimize chunk reuse:

- already-used chunks in the current blueprint run are excluded on early attempts
- chunks from failed attempts are excluded on later attempts
- chunks used in previous runs are penalized
- rescue mode broadens retrieval only after normal attempts fail

This makes the system less likely to reuse the same chunk across MCQ, True/False, Short Answer, and Essay slots.

## 17. Validation and Quality Control

The project includes multiple layers of post-generation control.

### Validation Types

- grounding
- distractor quality (MCQ)
- difficulty classification
- Bloom classification
- triviality
- correctness verification
- difficulty downgrade audit

### Grounding

Every saved question should have supporting chunk references. `QuestionSource` rows make the generated content traceable back to the course material.

### Triviality and Difficulty Gates

The system rejects weak questions before saving when they do not match the requested difficulty.

Examples:

- a hard question should require scenario reasoning, inference, consequence analysis, exceptions, or non-obvious application
- a medium question should require more than direct recall
- vague "common sense" style questions are rejected

### Difficulty Downgrade Behavior

If the system cannot reliably meet the requested difficulty after multiple attempts, the final standard attempt may accept a lower-difficulty but still grounded question. When this happens:

- the saved `Question.difficulty` reflects the accepted difficulty
- a `difficulty_downgrade` validation row is stored
- the job summary includes a downgraded question count
- the generation page shows a visible notice to the professor

This is a deliberate design choice: prefer transparent degradation over silently pretending a weak question is hard.

### Correctness and Distractors

For MCQ and True/False questions, the system performs extra checks such as:

- correct option consistency
- ambiguous answer detection
- duplicate distractor prevention
- structural validation of options

## 18. Diversity and Rejection Memory

The system tries not to regenerate the same question over and over.

It uses:

- exact fingerprints of normalized question text
- embeddings for near-duplicate detection
- a blacklist table for rejected content
- recent question history for cross-run deduplication

This is important for a real exam-generation workflow because repetition lowers educational quality and wastes review effort.

## 19. Human Review Workflow

The generation pipeline produces draft questions, not final exam content.

Question statuses:

- `draft`
- `reviewed`
- `approved`
- `rejected`

The professor can:

- inspect the full question
- inspect its sources
- edit question content
- approve it
- reject it
- replace it with another candidate

This human review stage is central to the system's trust model.

## 20. Exam Assembly

After question review, the professor can assemble an exam from approved questions.

The exam assembly subsystem:

- collects approved questions for a blueprint or a specific question set
- creates an `Exam` row
- creates ordered `ExamQuestion` rows
- lets the professor reorder questions
- lets the professor assign or edit points

The final exam remains editable after assembly.

## 21. Export Subsystem

The export system produces:

- exam document
- answer key document

### Export Process

1. Load the assembled exam and ordered exam questions.
2. Render Jinja2 LaTeX templates.
3. Write `.tex` files to `Backend/data/exports/<exam_id>/`.
4. If `pdflatex` is available:
   - compile to PDF
   - return PDF export records
5. Otherwise:
   - keep `.tex`
   - return `.tex` export records

### PDF Tooling

- Docker backend includes TeX Live.
- On Windows, local export requires a LaTeX distribution such as MiKTeX.

## 22. Student Practice Mode

Student practice reuses the same knowledge base and generation pipeline but with a different interaction model.

The student can request:

- selected question types
- selected topics or full-course mode
- number of questions
- optional target difficulty

Current MVP note:

- student practice is primarily implemented for MCQ and True/False generation
- short answer and essay practice are not the main supported path yet

## 23. LLM Provider Strategy

The system has a provider abstraction layer. This makes the architecture flexible and cost-aware.

Benefits:

- switch providers without rewriting business logic
- use mock mode for development/tests
- use local models through Ollama
- use remote providers for production quality
- configure fallback chains for resilience

Example fallback pattern:

- primary: `openai_compatible`
- fallback: `cerebras`
- second fallback: `gemini`

## 24. Why This Is More Than Prompt Engineering

An important thesis point is that the project does not rely only on a prompt.

The quality of the system comes from the combination of:

- document preprocessing
- chunk classification
- semantic retrieval
- traceable sources
- topic structure
- difficulty-aware generation
- validation rules
- diversity controls
- professor review
- exam assembly and export

The architecture is therefore a controlled AI workflow, not just a one-shot LLM call.

## 25. Local Development

### Option A: Docker

From the project root:

```powershell
docker compose up -d
```

This starts:

- PostgreSQL + pgvector
- Redis
- FastAPI backend
- Celery worker
- frontend

Default ports:

- backend: `8001`
- frontend: `80`
- PostgreSQL: `5433`
- Redis: `6379`

### Option B: Local Windows Development

The current local workflow in this repository is:

1. Start the database stack:

```powershell
docker compose up -d
```

2. Start the backend:

```powershell
cd "D:\Miskolc Thesis\Backend"
$env:Path += ";C:\Users\Oussema\AppData\Local\Programs\MiKTeX\miktex\bin\x64"
& "d:\Miskolc Thesis\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

3. Start the worker:

```powershell
cd "D:\Miskolc Thesis\Backend"
$env:Path += ";C:\Users\Oussema\AppData\Local\Programs\MiKTeX\miktex\bin\x64"
& "d:\Miskolc Thesis\.venv\Scripts\python.exe" -m celery -A app.workers.celery_app worker --loglevel=info --pool=solo --without-gossip --without-mingle
```

4. Start the frontend separately if you want the Vite dev server:

```powershell
cd "D:\Miskolc Thesis\Frontend"
npm install
npm run dev
```

## 26. Environment Variables

Important environment variables include:

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

The frontend app expects `VITE_API_BASE_URL` to be the backend base URL, and then appends `/api/v1` internally.

Example:

- local backend: `http://localhost:8001`
- not `http://localhost:8001/api/v1`

## 27. Important Design Decisions

### 27.1 Human-in-the-Loop

The system does not aim to remove the professor. It aims to accelerate the professor's work while preserving academic control.

### 27.2 Traceability

Each question stores supporting snippets and chunk references. This is crucial for trust, review, and thesis evaluation.

### 27.3 Background Processing

Document processing and blueprint generation can be expensive and slow. Moving them to Celery keeps the UI responsive and gives the user visible progress.

### 27.4 Explicit Quality Gates

Weak, trivial, vague, or duplicate questions should be filtered before the professor sees them. This reduces review burden.

### 27.5 Controlled Failure and Transparency

When the available material cannot reliably support the requested difficulty, the system records and surfaces the downgrade instead of silently mislabeling the question.

## 28. Current Limitations

- Text-first PDF extraction means image-heavy slides, formulas embedded as images, and diagrams may not be fully represented.
- Question quality still depends on the quality and specificity of the source material.
- Student practice currently emphasizes MCQ and True/False more than long-form answers.
- Export quality depends on the local LaTeX installation when not using Docker.
- LLM provider quality, latency, and cost vary significantly.
- Some validation steps are heuristic and may still miss edge cases.

## 29. Future Improvements

- OCR support for scanned or image-heavy PDFs
- stronger topic refinement and topic editing tools
- richer student practice analytics and scoring
- more advanced Bloom-aware generation
- rubric-aware essay grading assistance
- multilingual support
- stronger faculty-side review analytics
- better diagram/formula extraction
- more robust benchmark datasets for evaluation

## 30. What Makes This Project Suitable for a Thesis

This project combines:

- software engineering
- AI system design
- retrieval-augmented generation
- educational technology
- asynchronous distributed processing
- human-AI interaction

A thesis based on this project can discuss:

- architecture design for trustworthy educational AI
- retrieval quality and chunking effects on question quality
- methods for difficulty control in generated assessment items
- grounded generation versus hallucinated generation
- the role of human review in academic AI systems
- trade-offs between automation, cost, latency, and quality

## 31. Short Thesis-Ready Description

This project is an AI-assisted exam generation platform that transforms university course PDFs into a structured, searchable knowledge base and uses retrieval-augmented language model generation to produce exam questions. The system supports topic extraction, blueprint-driven assessment design, semantic retrieval with pgvector, multi-stage question validation, diversity control, professor review, exam assembly, and export to LaTeX/PDF. It is designed as a human-in-the-loop educational AI system in which generated questions remain grounded in course material and are auditable through explicit source tracking.
