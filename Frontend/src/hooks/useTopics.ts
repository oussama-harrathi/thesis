import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { topicsApi } from '../lib/api'
import type { TopicCreate, TopicUpdate } from '../types/api'

// ── Query keys ────────────────────────────────────────────────────

export const topicKeys = {
  byCourse: (courseId: string | undefined) =>
    ['topics', 'course', courseId] as const,
}

// ── Queries ───────────────────────────────────────────────────────

export function useCourseTopics(courseId: string | undefined) {
  return useQuery({
    queryKey: topicKeys.byCourse(courseId),
    queryFn: () => topicsApi.listByCourse(courseId!),
    enabled: !!courseId,
  })
}

// ── Mutations ─────────────────────────────────────────────────────

export function useCreateTopic(courseId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: TopicCreate) => topicsApi.create(courseId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: topicKeys.byCourse(courseId) })
    },
  })
}

export function useUpdateTopic(courseId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ topicId, body }: { topicId: string; body: TopicUpdate }) =>
      topicsApi.update(topicId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: topicKeys.byCourse(courseId) })
    },
  })
}

export function useDeleteTopic(courseId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (topicId: string) => topicsApi.delete(topicId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: topicKeys.byCourse(courseId) })
    },
  })
}

export function useReextractTopics(courseId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => topicsApi.reextract(courseId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: topicKeys.byCourse(courseId) })
    },
  })
}
