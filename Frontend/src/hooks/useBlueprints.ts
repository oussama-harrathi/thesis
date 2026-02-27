import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { blueprintsApi } from '../lib/api'
import type { BlueprintCreateRequest } from '../types/api'

export function useCourseBlueprints(courseId: string | undefined) {
  return useQuery({
    queryKey: ['blueprints', 'course', courseId],
    queryFn: () => blueprintsApi.listByCourse(courseId!),
    enabled: Boolean(courseId),
  })
}

export function useBlueprint(blueprintId: string | null) {
  return useQuery({
    queryKey: ['blueprints', blueprintId],
    queryFn: () => blueprintsApi.get(blueprintId!),
    enabled: Boolean(blueprintId),
  })
}

export function useCreateBlueprint(courseId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: BlueprintCreateRequest) =>
      blueprintsApi.create(courseId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['blueprints', 'course', courseId] })
    },
  })
}

export function useGenerateFromBlueprint() {
  return useMutation({
    mutationFn: (blueprintId: string) => blueprintsApi.generate(blueprintId),
  })
}
