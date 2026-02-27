import { useQuery } from '@tanstack/react-query'
import { jobsApi } from '../lib/api'

/**
 * Poll a job by ID.
 *
 * Automatically refetches every `refetchInterval` ms (default 2000) while
 * the job is pending or running.  Stops polling once completed or failed.
 */
export function useJob(
  jobId: string | null,
  options?: { refetchInterval?: number },
) {
  return useQuery({
    queryKey: ['jobs', jobId],
    queryFn: () => jobsApi.get(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'completed' || status === 'failed') return false
      return options?.refetchInterval ?? 2000
    },
  })
}
