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
  created_at: string
  updated_at: string
}

export interface TopicCreate {
  name: string
}

export interface TopicUpdate {
  name: string
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
export type QuestionStatus = 'draft' | 'approved' | 'rejected'

export interface Question {
  id: string
  question_set_id: string
  type: QuestionType
  body: string
  difficulty: Difficulty
  bloom_level: BloomLevel
  status: QuestionStatus
  created_at: string
}

// ── Jobs ──────────────────────────────────────────────────────────

export type JobStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface Job {
  id: string
  status: JobStatus
  progress: number
  message: string | null
  created_at: string
}
