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
    apiRequest<Topic[]>(`/courses/${courseId}/topics`),

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
}
