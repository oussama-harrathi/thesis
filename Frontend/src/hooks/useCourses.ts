/**
 * React Query hooks for the Course resource.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { coursesApi } from '../lib/api'
import type { CourseCreate, CourseUpdate } from '../types/api'

export const courseKeys = {
  all: ['courses'] as const,
  detail: (id: string) => ['courses', id] as const,
}

/** Fetch all courses. */
export function useCourses() {
  return useQuery({
    queryKey: courseKeys.all,
    queryFn: () => coursesApi.list(),
  })
}

/** Fetch a single course by id. */
export function useCourse(courseId: string | undefined) {
  return useQuery({
    queryKey: courseKeys.detail(courseId ?? ''),
    queryFn: () => coursesApi.get(courseId!),
    enabled: Boolean(courseId),
  })
}

/** Create a new course; invalidates the list on success. */
export function useCreateCourse() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CourseCreate) => coursesApi.create(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: courseKeys.all }),
  })
}

/** Partially update a course; invalidates list + detail on success. */
export function useUpdateCourse(courseId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CourseUpdate) => coursesApi.update(courseId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: courseKeys.all })
      qc.invalidateQueries({ queryKey: courseKeys.detail(courseId) })
    },
  })
}
