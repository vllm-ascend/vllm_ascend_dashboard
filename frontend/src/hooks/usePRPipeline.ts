import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as api from '../services/prPipeline'

const invalidatePRPipelineQueries = (queryClient: ReturnType<typeof useQueryClient>) => {
  queryClient.invalidateQueries({
    predicate: (query) => {
      const key = query.queryKey[0]
      return typeof key === 'string' && key.startsWith('pr-pipeline')
    },
  })
}

export const usePRPipelineOverview = (days?: number) => {
  return useQuery({
    queryKey: ['pr-pipeline-overview', days],
    queryFn: () => api.getOverview(days),
  })
}

export const usePRPipelineKanban = (state?: string, includeDraft?: boolean, limitPerStage?: number) => {
  return useQuery({
    queryKey: ['pr-pipeline-kanban', state, includeDraft, limitPerStage],
    queryFn: () => api.getKanban(state, includeDraft, limitPerStage),
  })
}

export const usePRPipelineList = (params?: {
  state?: string
  pipeline_stage?: string
  author?: string
  review_status?: string
  ci_status?: string
  is_draft?: boolean
  base_branch?: string
  date_from?: string
  date_to?: string
  label?: string
  search?: string
  sort_by?: string
  sort_order?: string
  page?: number
  page_size?: number
}) => {
  return useQuery({
    queryKey: ['pr-pipeline-list', params],
    queryFn: () => api.getList(params),
  })
}

export const usePRPipelineMetrics = (days?: number) => {
  return useQuery({
    queryKey: ['pr-pipeline-metrics', days],
    queryFn: () => api.getMetrics(days),
  })
}

export const usePRPipelineContributors = (days?: number, type?: string, skip?: number, limit?: number, company?: string, sortBy?: string) => {
  return useQuery({
    queryKey: ['pr-pipeline-contributors', days, type, skip, limit, company, sortBy],
    queryFn: () => api.getContributors(days, type, skip, limit, company, sortBy),
  })
}

export const usePRPipelineTrends = (days?: number) => {
  return useQuery({
    queryKey: ['pr-pipeline-trends', days],
    queryFn: () => api.getTrends(days),
  })
}

export const usePRDetail = (prNumber?: number) => {
  return useQuery({
    queryKey: ['pr-pipeline-detail', prNumber],
    queryFn: () => api.getPRDetail(prNumber!),
    enabled: !!prNumber,
  })
}

export const usePRPipelineSync = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (daysBack?: number) => api.syncPRPipeline(daysBack),
    onSuccess: () => {
      invalidatePRPipelineQueries(queryClient)
    },
  })
}

export const usePRPipelineSyncStatus = () => {
  return useQuery({
    queryKey: ['pr-pipeline-sync-status'],
    queryFn: () => api.getSyncStatus(),
    refetchInterval: 30_000,
  })
}

export const usePRPipelineHistoricalSync = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (params?: { phases?: string[]; monthsBack?: number }) =>
      api.historicalSyncPRPipeline(params?.phases, params?.monthsBack),
    onSuccess: () => {
      invalidatePRPipelineQueries(queryClient)
    },
  })
}

export function usePRDiagnosis() {
  return useMutation({
    mutationFn: (prNumber: number) => api.diagnosePR(prNumber),
  })
}
