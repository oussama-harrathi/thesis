// ── Common ────────────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  size: number
}

// ── Courses ───────────────────────────────────────────────────────

export interface Course {
  id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

export interface CourseCreate {
  name: string
  description?: string
}

export interface CourseUpdate {
  name?: string
  description?: string | null
}

// ── Documents ─────────────────────────────────────────────────────

export type DocumentStatus =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'failed'

export interface Document {
  id: string
  course_id: string
  filename: string            // storage filename
  original_filename: string  // user-supplied name
  file_path: string
  file_size: number | null
  mime_type: string | null
  status: DocumentStatus
  created_at: string
  updated_at: string
}

export interface DocumentUploadResponse {
  document: Document
  job_id: string
  job_status: string
  checksum_sha256: string
}

// ── Topics ────────────────────────────────────────────────────────

export interface Topic {
  id: string
  course_id: string
  name: string
  is_auto_extracted: boolean
  source: string | null
  level: string | null          // 'CHAPTER' | 'SECTION' | 'SUBSECTION'
  parent_topic_id: string | null
  coverage_score: number | null
  chunk_count: number
  is_noisy_suspect: boolean
  created_at: string
  updated_at: string
}

export interface TopicCreate {
  name: string
}

export interface TopicUpdate {
  name: string
}

export interface ExtractionMeta {
  chosen_method: string
  overall_confidence: number
  is_low_confidence: boolean
  coverage_ratio: number
  topic_count: number
}

export interface TopicListResponse {
  topics: Topic[]
  extraction_meta: ExtractionMeta | null
}

// ── Questions ─────────────────────────────────────────────────────

export type QuestionType = 'mcq' | 'true_false' | 'short_answer' | 'essay'
export type Difficulty = 'easy' | 'medium' | 'hard'
export type BloomLevel =
  | 'remember'
  | 'understand'
  | 'apply'
  | 'analyze'
  | 'evaluate'
  | 'create'
export type QuestionStatus = 'draft' | 'reviewed' | 'approved' | 'rejected'

/** Lightweight row returned by GET /courses/{id}/questions */
export interface QuestionListItem {
  id: string
  question_set_id: string
  type: QuestionType
  body: string
  difficulty: Difficulty
  bloom_level: BloomLevel | null
  status: QuestionStatus
  created_at: string
  blueprint_id: string | null
  blueprint_title: string | null
}

/** One MCQ option from GET /questions/{id} */
export interface MCQOptionResponse {
  id: string
  label: string   // A | B | C | D
  text: string
  is_correct: boolean
}

/** One source snippet from GET /questions/{id} */
export interface QuestionSourceResponse {
  id: string
  chunk_id: string | null
  snippet: string
}

/** Full question detail returned by GET /questions/{id} */
export interface QuestionDetail {
  id: string
  question_set_id: string
  type: QuestionType
  body: string
  correct_answer: string | null
  explanation: string | null
  difficulty: Difficulty
  bloom_level: BloomLevel | null
  status: QuestionStatus
  model_name: string | null
  prompt_version: string | null
  insufficient_context: boolean
  created_at: string
  updated_at: string
  mcq_options: MCQOptionResponse[]
  sources: QuestionSourceResponse[]
}

// ── Question mutation payloads ─────────────────────────────────────

export interface MCQOptionUpdate {
  id?: string
  label?: string   // A | B | C | D
  text?: string
  is_correct?: boolean
}

export interface QuestionUpdateRequest {
  body?: string
  correct_answer?: string
  explanation?: string
  difficulty?: Difficulty
  bloom_level?: BloomLevel
  mcq_options?: MCQOptionUpdate[]
}

export interface RejectRequest {
  reason?: string
}

export interface QuestionStatusResponse {
  id: string
  status: QuestionStatus
}

// ── Question replacement ───────────────────────────────────────────

export interface ReplacementCandidateResponse {
  id: string
  type: QuestionType
  body: string
  difficulty: Difficulty
  bloom_level: BloomLevel | null
  status: QuestionStatus
  blueprint_id: string | null
  blueprint_title: string | null
}

export interface ReplaceQuestionRequest {
  replacement_question_id: string
}

// ── Exams ─────────────────────────────────────────────────────────

/** One slot in an assembled exam */
export interface ExamQuestion {
  id: string
  exam_id: string
  question_id: string
  position: number
  points: number | null
  question: QuestionDetail
}

/** Full assembled exam with ordered question slots */
export interface Exam {
  id: string
  blueprint_id: string
  course_id: string
  title: string
  description: string | null
  total_points: number | null
  created_at: string
  updated_at: string
  exam_questions: ExamQuestion[]
}

/** Lightweight exam row for list views */
export interface ExamListItem {
  id: string
  blueprint_id: string
  course_id: string
  title: string
  description: string | null
  total_points: number | null
  question_count: number
  created_at: string
  updated_at: string
}

// ── Exam mutation payloads ─────────────────────────────────────────

export interface AssembleExamRequest {
  title: string
  description?: string
  default_points_per_question?: number
  question_set_id?: string
}

export interface AddExamQuestionRequest {
  question_id: string
  points?: number
}

export interface ReorderItem {
  exam_question_id: string
  position: number
  points?: number
}

export interface ReorderExamQuestionsRequest {
  items: ReorderItem[]
}

// ── Practice (Student) ───────────────────────────────────────────

export interface CreatePracticeSetRequest {
  course_id: string
  topic_ids?: string[]
  question_types: QuestionType[]
  count: number
  difficulty?: Difficulty
  title?: string
}

export interface PracticeSetResponse {
  id: string
  course_id: string
  mode: string
  title: string | null
  created_at: string
  generated: number
  questions: QuestionDetail[]
}

// ── Jobs ──────────────────────────────────────────────────────────

export type JobStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface Job {
  id: string
  status: JobStatus
  progress: number
  message: string | null
  /** JSON-encoded summary written by the worker: {requested,generated,failed,failure_reasons} */
  error: string | null
  created_at: string
}

export interface JobSummary {
  requested: number
  generated: number
  failed: number
  failure_reasons: string[]
}

// ── Blueprints ────────────────────────────────────────────────────

/** Lightweight blueprint row returned by GET /courses/{id}/blueprints */
export interface BlueprintListItem {
  id: string
  course_id: string
  title: string
  description: string | null
  total_questions: number
  total_points: number
  duration_minutes: number | null
  created_at: string
  updated_at: string
}

export interface QuestionTypeCounts {
  mcq: number
  true_false: number
  short_answer: number
  essay: number
}

export interface DifficultyMix {
  easy: number
  medium: number
  hard: number
}

export interface TopicMix {
  mode: 'auto' | 'manual'
  topics: Array<{ topic_id: string; question_count: number }>
}

export interface BlueprintConfig {
  question_counts: QuestionTypeCounts
  difficulty_mix: DifficultyMix
  bloom_mix: null
  topic_mix: TopicMix
  total_points: number
  duration_minutes: number | null
}

/** Full blueprint detail returned by GET /blueprints/{id} */
export interface BlueprintResponse {
  id: string
  course_id: string
  title: string
  description: string | null
  config: BlueprintConfig
  created_at: string
  updated_at: string
}

export interface BlueprintCreateRequest {
  title: string
  description?: string
  config: BlueprintConfig
}

export interface StartGenerationResponse {
  job_id: string
  question_set_id: string
  blueprint_id: string
  status: string
}

export interface JobResponse {
  id: string
  type: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  document_id: string | null
  course_id: string | null
  blueprint_id: string | null
  progress: number
  message: string | null
  error: string | null
  created_at: string
  updated_at: string
}

// ── Exports ───────────────────────────────────────────────────────

export type ExportType = 'exam_pdf' | 'answer_key_pdf' | 'exam_tex' | 'answer_key_tex'
export type ExportStatus = 'pending' | 'completed' | 'failed'

export interface ExportRecord {
  id: string
  exam_id: string
  export_type: ExportType
  status: ExportStatus
  filename: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface ExportPairResponse {
  exam_export: ExportRecord
  answer_key_export: ExportRecord
}
