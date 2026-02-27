/**
 * React Query hooks for the Question resource.
 *
 * List:    useCourseQuestions(courseId, filters)
 * Detail:  useQuestion(questionId)
 * Mutate:  useUpdateQuestion, useApproveQuestion, useRejectQuestion
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { questionsApi, type ListQuestionsParams } from '../lib/api'
import type { QuestionUpdateRequest, RejectRequest } from '../types/api'

// ── Query keys ────────────────────────────────────────────────────

export const questionKeys = {
  /** All questions for a course (any filter) */
  byCourse: (courseId: string) => ['questions', 'course', courseId] as const,

  /** Questions for a course WITH specific filter params */
  byCourseFiltered: (courseId: string, params: ListQuestionsParams) =>
    ['questions', 'course', courseId, params] as const,

  /** Single question detail */
  detail: (questionId: string) => ['questions', questionId] as const,
}

// ── Queries ───────────────────────────────────────────────────────

/**
 * Fetch the question list for a course.
 * Server-side filters: type, difficulty, status.
 */
export function useCourseQuestions(
  courseId: string | undefined,
  params: ListQuestionsParams = {},
) {
  return useQuery({
    queryKey: questionKeys.byCourseFiltered(courseId ?? '', params),
    queryFn: () => questionsApi.listByCourse(courseId!, params),
    enabled: Boolean(courseId),
    staleTime: 10_000,
  })
}

/**
 * Fetch full question detail (with MCQ options + source snippets).
 */
export function useQuestion(questionId: string | null) {
  return useQuery({
    queryKey: questionKeys.detail(questionId ?? ''),
    queryFn: () => questionsApi.get(questionId!),
    enabled: Boolean(questionId),
    staleTime: 10_000,
  })
}

// ── Mutations ─────────────────────────────────────────────────────

/**
 * PATCH /api/v1/questions/{questionId}
 * Invalidates both the list (for the course) and the detail entry.
 */
export function useUpdateQuestion(courseId: string, questionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: QuestionUpdateRequest) =>
      questionsApi.update(questionId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: questionKeys.byCourse(courseId) })
      qc.invalidateQueries({ queryKey: questionKeys.detail(questionId) })
    },
  })
}

/**
 * POST /api/v1/questions/{questionId}/approve
 */
export function useApproveQuestion(courseId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (questionId: string) => questionsApi.approve(questionId),
    onSuccess: (_data, questionId) => {
      qc.invalidateQueries({ queryKey: questionKeys.byCourse(courseId) })
      qc.invalidateQueries({ queryKey: questionKeys.detail(questionId) })
    },
  })
}

/**
 * POST /api/v1/questions/{questionId}/reject
 */
export function useRejectQuestion(courseId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ questionId, body }: { questionId: string; body?: RejectRequest }) =>
      questionsApi.reject(questionId, body),
    onSuccess: (_data, { questionId }) => {
      qc.invalidateQueries({ queryKey: questionKeys.byCourse(courseId) })
      qc.invalidateQueries({ queryKey: questionKeys.detail(questionId) })
    },
  })
}
