/**
 * Typed API client.
 *
 * All fetch calls go through `apiRequest`. Import and use the typed helpers
 * in React Query hooks — do NOT call fetch directly from components.
 *
 * Base URL is read from the Vite environment variable VITE_API_BASE_URL.
 */

import type {
  Course,
  CourseCreate,
  CourseUpdate,
  Document,
  DocumentUploadResponse,
  Topic,
  TopicCreate,
  TopicUpdate,
  TopicListResponse,
  QuestionListItem,
  QuestionDetail,
  QuestionUpdateRequest,
  RejectRequest,
  QuestionStatusResponse,
  ReplacementCandidateResponse,
  ReplaceQuestionRequest,
  Exam,
  ExamListItem,
  AssembleExamRequest,
  AddExamQuestionRequest,
  ReorderExamQuestionsRequest,
  ExamQuestion,
  BlueprintListItem,
  BlueprintResponse,
  BlueprintCreateRequest,
  StartGenerationResponse,
  JobResponse,
  CreatePracticeSetRequest,
  PracticeSetResponse,
  ExportRecord,
  ExportPairResponse,
} from '../types/api'

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string) ?? ''

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function apiRequest<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const url = `${BASE_URL}/api/v1${path}`
  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  })

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new ApiError(res.status, text)
  }

  return res.json() as Promise<T>
}

// ── Health ────────────────────────────────────────────────────────
export const healthApi = {
  get: () => apiRequest<{ status: string; app: string; version: string }>('/health'),
  db: () => apiRequest<{ status: string; database_connected: boolean }>('/health/db'),
}

// ── Courses ───────────────────────────────────────────────────────
export const coursesApi = {
  list: () =>
    apiRequest<Course[]>('/courses'),

  get: (courseId: string) =>
    apiRequest<Course>(`/courses/${courseId}`),

  create: (body: CourseCreate) =>
    apiRequest<Course>('/courses', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  update: (courseId: string, body: CourseUpdate) =>
    apiRequest<Course>(`/courses/${courseId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  delete: (courseId: string) =>
    fetch(`${BASE_URL}/api/v1/courses/${courseId}`, { method: 'DELETE' }).then(async (res) => {
      if (!res.ok && res.status !== 204) {
        const text = await res.text().catch(() => res.statusText)
        throw new ApiError(res.status, text)
      }
    }),
}

// ── Documents ─────────────────────────────────────────────────────
export const documentsApi = {
  /**
   * Upload a PDF to a course.
   * Uses FormData — do NOT pass Content-Type header (browser sets it with boundary).
   */
  upload: (courseId: string, file: File): Promise<DocumentUploadResponse> => {
    const url = `${BASE_URL}/api/v1/courses/${courseId}/documents`
    const form = new FormData()
    form.append('file', file)
    return fetch(url, { method: 'POST', body: form }).then(async (res) => {
      if (!res.ok) {
        const text = await res.text().catch(() => res.statusText)
        throw new ApiError(res.status, text)
      }
      return res.json() as Promise<DocumentUploadResponse>
    })
  },

  listByCourse: (courseId: string) =>
    apiRequest<Document[]>(`/courses/${courseId}/documents`),

  delete: (documentId: string) =>
    fetch(`${(import.meta.env.VITE_API_BASE_URL as string) ?? ''}/api/v1/documents/${documentId}`, {
      method: 'DELETE',
    }).then(async (res) => {
      if (!res.ok && res.status !== 204) {
        const text = await res.text().catch(() => res.statusText)
        throw new ApiError(res.status, text)
      }
    }),
}

// ── Topics ────────────────────────────────────────────────────────
export const topicsApi = {
  listByCourse: (courseId: string) =>
    apiRequest<TopicListResponse>(`/courses/${courseId}/topics`),

  create: (courseId: string, body: TopicCreate) =>
    apiRequest<Topic>(`/courses/${courseId}/topics`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  update: (topicId: string, body: TopicUpdate) =>
    apiRequest<Topic>(`/topics/${topicId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  delete: (topicId: string) =>
    fetch(`${(import.meta.env.VITE_API_BASE_URL as string) ?? ''}/api/v1/topics/${topicId}`, {
      method: 'DELETE',
    }).then(async (res) => {
      if (!res.ok && res.status !== 204) {
        const text = await res.text().catch(() => res.statusText)
        throw new ApiError(res.status, text)
      }
    }),

  reextract: (courseId: string) =>
    apiRequest<TopicListResponse>(`/courses/${courseId}/topics/reextract`, {
      method: 'POST',
    }),
}

// ── Questions ─────────────────────────────────────────────────────

export interface ListQuestionsParams {
  type?: string
  difficulty?: string
  status?: string
  limit?: number
  offset?: number
}

export const questionsApi = {
  /**
   * List questions for a course with optional server-side filters.
   * GET /api/v1/courses/{courseId}/questions
   */
  listByCourse: (courseId: string, params: ListQuestionsParams = {}) => {
    const qs = new URLSearchParams()
    if (params.type) qs.set('type', params.type)
    if (params.difficulty) qs.set('difficulty', params.difficulty)
    if (params.status) qs.set('status', params.status)
    if (params.limit != null) qs.set('limit', String(params.limit))
    if (params.offset != null) qs.set('offset', String(params.offset))
    const query = qs.toString() ? `?${qs.toString()}` : ''
    return apiRequest<QuestionListItem[]>(`/courses/${courseId}/questions${query}`)
  },

  /** GET /api/v1/questions/{questionId} — full detail with options + sources */
  get: (questionId: string) =>
    apiRequest<QuestionDetail>(`/questions/${questionId}`),

  /** PATCH /api/v1/questions/{questionId} */
  update: (questionId: string, body: QuestionUpdateRequest) =>
    apiRequest<QuestionDetail>(`/questions/${questionId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  /** POST /api/v1/questions/{questionId}/approve */
  approve: (questionId: string) =>
    apiRequest<QuestionStatusResponse>(`/questions/${questionId}/approve`, {
      method: 'POST',
    }),

  /** POST /api/v1/questions/{questionId}/reject */
  reject: (questionId: string, body: RejectRequest = {}) =>
    apiRequest<QuestionStatusResponse>(`/questions/${questionId}/reject`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /**
   * GET /api/v1/courses/{courseId}/questions/replacement-candidates
   * Returns approved same-type questions not yet in the target blueprint.
   */
  listReplacementCandidates: (
    courseId: string,
    type: string,
    excludeBlueprintId: string,
  ) => {
    const qs = new URLSearchParams({ type, exclude_blueprint_id: excludeBlueprintId })
    return apiRequest<ReplacementCandidateResponse[]>(
      `/courses/${courseId}/questions/replacement-candidates?${qs.toString()}`,
    )
  },

  /**
   * POST /api/v1/blueprints/{blueprintId}/questions/{questionId}/replace
   * Swaps a question in a blueprint for an approved replacement.
   */
  replaceInBlueprint: (
    blueprintId: string,
    questionId: string,
    body: ReplaceQuestionRequest,
  ) =>
    fetch(
      `${(import.meta.env.VITE_API_BASE_URL as string) ?? ''}/api/v1/blueprints/${blueprintId}/questions/${questionId}/replace`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    ).then(async (res) => {
      if (!res.ok && res.status !== 204) {
        const text = await res.text().catch(() => res.statusText)
        throw new ApiError(res.status, text)
      }
    }),
}

// ── Blueprints ────────────────────────────────────────────────────

export const blueprintsApi = {
  /** GET /api/v1/courses/{courseId}/blueprints */
  listByCourse: (courseId: string) =>
    apiRequest<BlueprintListItem[]>(`/courses/${courseId}/blueprints`),

  /** POST /api/v1/courses/{courseId}/blueprints */
  create: (courseId: string, body: BlueprintCreateRequest) =>
    apiRequest<BlueprintResponse>(`/courses/${courseId}/blueprints`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** GET /api/v1/blueprints/{blueprintId} */
  get: (blueprintId: string) =>
    apiRequest<BlueprintResponse>(`/blueprints/${blueprintId}`),

  /** POST /api/v1/blueprints/{blueprintId}/generate */
  generate: (blueprintId: string) =>
    apiRequest<StartGenerationResponse>(`/blueprints/${blueprintId}/generate`, {
      method: 'POST',
    }),

  /** DELETE /api/v1/blueprints/{blueprintId} */
  delete: (blueprintId: string) =>
    apiRequest<void>(`/blueprints/${blueprintId}`, { method: 'DELETE' }),
}

// ── Jobs ─────────────────────────────────────────────────────────

export const jobsApi = {
  /** GET /api/v1/jobs/{jobId} */
  get: (jobId: string) =>
    apiRequest<JobResponse>(`/jobs/${jobId}`),
}

// ── Exams ─────────────────────────────────────────────────────────

export const examsApi = {
  /** POST /api/v1/blueprints/{blueprintId}/assemble */
  assemble: (blueprintId: string, body: AssembleExamRequest) =>
    apiRequest<Exam>(`/blueprints/${blueprintId}/assemble`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** GET /api/v1/blueprints/{blueprintId}/exams */
  listByBlueprint: (blueprintId: string) =>
    apiRequest<ExamListItem[]>(`/blueprints/${blueprintId}/exams`),

  /** GET /api/v1/exams/{examId} */
  get: (examId: string) =>
    apiRequest<Exam>(`/exams/${examId}`),

  /** POST /api/v1/exams/{examId}/questions */
  addQuestion: (examId: string, body: AddExamQuestionRequest) =>
    apiRequest<ExamQuestion>(`/exams/${examId}/questions`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** PATCH /api/v1/exams/{examId}/questions/reorder */
  reorder: (examId: string, body: ReorderExamQuestionsRequest) =>
    apiRequest<Exam>(`/exams/${examId}/questions/reorder`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  /** DELETE /api/v1/exams/{examId}/questions/{examQuestionId} */
  removeQuestion: (examId: string, examQuestionId: string) =>
    fetch(
      `${(import.meta.env.VITE_API_BASE_URL as string) ?? ''}/api/v1/exams/${examId}/questions/${examQuestionId}`,
      { method: 'DELETE' },
    ).then(async (res) => {
      if (!res.ok && res.status !== 204) {
        const text = await res.text().catch(() => res.statusText)
        throw new ApiError(res.status, text)
      }
    }),
}

// ── Exports ──────────────────────────────────────────────────

export const exportsApi = {
  /** POST /api/v1/exams/{examId}/export — trigger generation; returns both records */
  trigger: (examId: string) =>
    apiRequest<ExportPairResponse>(`/exams/${examId}/export`, { method: 'POST' }),

  /** GET /api/v1/exams/{examId}/exports — list export records, newest first */
  listByExam: (examId: string) =>
    apiRequest<ExportRecord[]>(`/exams/${examId}/exports`),

  /** Construct the download URL (opened via window.open / anchor) */
  downloadUrl: (exportId: string) =>
    `${(import.meta.env.VITE_API_BASE_URL as string) ?? ''}/api/v1/exports/${exportId}/download`,
}

// ── Student Practice ──────────────────────────────────────────

export const practiceApi = {
  /** POST /api/v1/student/practice-sets */
  create: (body: CreatePracticeSetRequest) =>
    apiRequest<PracticeSetResponse>('/student/practice-sets', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** GET /api/v1/student/practice-sets/{questionSetId} */
  get: (questionSetId: string) =>
    apiRequest<PracticeSetResponse>(`/student/practice-sets/${questionSetId}`),
}
