/**
 * React Query hooks for the Export resource.
 *
 * useExamExports    – list all exports for an exam (auto-fetches, refetches every 5 s
 *                     while any export is still pending so the status refreshes)
 * useTriggerExport  – mutation to POST /exams/{examId}/export
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { exportsApi } from '../lib/api'
import type { ExportPairResponse, ExportRecord } from '../types/api'

// ── Query keys ───────────────────────────────────────────────────────────────

export const exportKeys = {
  all: ['exports'] as const,
  byExam: (examId: string) => ['exports', 'exam', examId] as const,
}

// ── Hooks ─────────────────────────────────────────────────────────────────────

/**
 * Fetch (and periodically refresh) the list of Export records for one exam.
 *
 * The list is polled every 5 s while any record is in `pending` status so that
 * freshly triggered exports surface their `completed` or `failed` state
 * without a manual page refresh.
 */
export function useExamExports(examId: string | undefined) {
  return useQuery<ExportRecord[]>({
    queryKey: exportKeys.byExam(examId ?? ''),
    queryFn: () => exportsApi.listByExam(examId!),
    enabled: !!examId,
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data) return false
      const hasPending = data.some((e) => e.status === 'pending')
      return hasPending ? 5_000 : false
    },
  })
}

/**
 * Mutation to trigger a new export pair (exam + answer key) for an exam.
 *
 * On success the exam's export list is invalidated so `useExamExports`
 * refetches automatically.
 */
export function useTriggerExport(examId: string | undefined) {
  const qc = useQueryClient()

  return useMutation<ExportPairResponse, Error>({
    mutationFn: () => exportsApi.trigger(examId!),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: exportKeys.byExam(examId ?? '') })
    },
  })
}
