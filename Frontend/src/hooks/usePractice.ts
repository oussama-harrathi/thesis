/**
 * React Query hooks for student practice sets.
 *
 * Hooks:
 *   usePracticeSet      – fetch a practice set by ID (enabled when ID is truthy)
 *   useCreatePracticeSet – mutation: POST /student/practice-sets
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { practiceApi } from '../lib/api'
import type { CreatePracticeSetRequest, PracticeSetResponse } from '../types/api'

// ── Query keys ────────────────────────────────────────────────────

export const practiceKeys = {
  all: ['practiceSets'] as const,
  detail: (id: string) => ['practiceSets', id] as const,
}

// ── Queries ───────────────────────────────────────────────────────

/**
 * Fetch a practice set with all questions.
 * Only runs when `questionSetId` is a non-empty string.
 */
export function usePracticeSet(questionSetId: string | null) {
  return useQuery({
    queryKey: practiceKeys.detail(questionSetId ?? ''),
    queryFn: () => practiceApi.get(questionSetId!),
    enabled: Boolean(questionSetId),
    staleTime: 60_000,        // practice sets are immutable after creation
    retry: 1,
  })
}

// ── Mutations ─────────────────────────────────────────────────────

/**
 * Create a new practice set.
 * On success the returned `PracticeSetResponse` is cached under its ID
 * so `usePracticeSet` can serve it immediately without a second network call.
 */
export function useCreatePracticeSet() {
  const queryClient = useQueryClient()

  return useMutation<PracticeSetResponse, Error, CreatePracticeSetRequest>({
    mutationFn: (body) => practiceApi.create(body),
    onSuccess: (data) => {
      // Seed the detail cache so the session page loads without a fetch round-trip.
      queryClient.setQueryData(practiceKeys.detail(data.id), data)
    },
  })
}
