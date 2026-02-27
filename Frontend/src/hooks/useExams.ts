/**
 * React Query hooks for the Exam resource.
 *
 * useExamsByBlueprint   – list exams for a blueprint
 * useExam               – full exam detail (with ordered questions)
 * useAssembleExam       – POST assemble
 * useAddExamQuestion    – POST add question
 * useReorderExam        – PATCH reorder/points
 * useRemoveExamQuestion – DELETE question slot
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { examsApi } from '../lib/api'
import type {
  AssembleExamRequest,
  AddExamQuestionRequest,
  ReorderExamQuestionsRequest,
} from '../types/api'

// ── Query keys ────────────────────────────────────────────────────

export const examKeys = {
  byBlueprint: (blueprintId: string) =>
    ['exams', 'blueprint', blueprintId] as const,
  detail: (examId: string) =>
    ['exams', examId] as const,
}

// ── Queries ───────────────────────────────────────────────────────

/** Fetch the list of exams for a blueprint (lightweight items). */
export function useExamsByBlueprint(blueprintId: string | undefined) {
  return useQuery({
    queryKey: examKeys.byBlueprint(blueprintId ?? ''),
    queryFn: () => examsApi.listByBlueprint(blueprintId!),
    enabled: Boolean(blueprintId),
    staleTime: 10_000,
  })
}

/** Fetch full exam detail with all ordered question slots. */
export function useExam(examId: string | undefined) {
  return useQuery({
    queryKey: examKeys.detail(examId ?? ''),
    queryFn: () => examsApi.get(examId!),
    enabled: Boolean(examId),
    staleTime: 10_000,
  })
}

// ── Mutations ─────────────────────────────────────────────────────

/**
 * POST /api/v1/blueprints/{blueprintId}/assemble
 * Creates an exam; invalidates the blueprint's exam list.
 */
export function useAssembleExam(blueprintId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AssembleExamRequest) =>
      examsApi.assemble(blueprintId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: examKeys.byBlueprint(blueprintId) })
    },
  })
}

/**
 * POST /api/v1/exams/{examId}/questions
 * Appends a question; invalidates the exam detail.
 */
export function useAddExamQuestion(examId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AddExamQuestionRequest) =>
      examsApi.addQuestion(examId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: examKeys.detail(examId) })
    },
  })
}

/**
 * PATCH /api/v1/exams/{examId}/questions/reorder
 * Updates positions/points; invalidates the exam detail.
 */
export function useReorderExam(examId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ReorderExamQuestionsRequest) =>
      examsApi.reorder(examId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: examKeys.detail(examId) })
    },
  })
}

/**
 * DELETE /api/v1/exams/{examId}/questions/{examQuestionId}
 * Invalidates the exam detail after deletion.
 */
export function useRemoveExamQuestion(examId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (examQuestionId: string) =>
      examsApi.removeQuestion(examId, examQuestionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: examKeys.detail(examId) })
    },
  })
}
