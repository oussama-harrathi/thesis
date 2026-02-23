/**
 * React Query hooks for the Document resource.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { documentsApi } from '../lib/api'

export const documentKeys = {
  byCourse: (courseId: string) => ['documents', 'course', courseId] as const,
}

/** Fetch all documents for a course. */
export function useCourseDocuments(courseId: string | undefined) {
  return useQuery({
    queryKey: documentKeys.byCourse(courseId ?? ''),
    queryFn: () => documentsApi.listByCourse(courseId!),
    enabled: Boolean(courseId),
  })
}

/** Upload a PDF to a course; invalidates the document list on success. */
export function useUploadDocument(courseId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => documentsApi.upload(courseId, file),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: documentKeys.byCourse(courseId) }),
  })
}

/** Delete a document; invalidates the document list on success. */
export function useDeleteDocument(courseId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (documentId: string) => documentsApi.delete(documentId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: documentKeys.byCourse(courseId) }),
  })
}
