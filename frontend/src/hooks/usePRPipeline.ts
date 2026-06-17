import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as api from '../services/prPipeline'

export const usePRPipelineOverview = (days?: number) => {
  return useQuery({
    queryKey: ['pr-pipeline-overview', days],
    queryFn: () => api.getPRPipelineOverview(days),
  })
}

export const usePRPipelineKanban = (state?: string, includeDraft?: boolean, limitPerStage?: number) => {
  return useQuery({
    queryKey: ['pr-pipeline-kanban', state, includeDraft, limitPerStage],
    queryFn: () => api.getPRPipelineKanban(state, includeDraft, limitPerStage),
  })
}

export const usePRPipelineList = (params?: api.PRPipelineListParams) => {
  return useQuery({
    queryKey: ['pr-pipeline-list', params],
    queryFn: () => api.getPRPipelineList(params),
  })
}

export const usePRPipelineMetrics = (days?: number) => {
  return useQuery({
    queryKey: ['pr-pipeline-metrics', days],
    queryFn: () => api.getPRPipelineMetrics(days),
  })
}

export const usePRPipelineContributors = (days?: number, type?: string, limit?: number) => {
  return useQuery({
    queryKey: ['pr-pipeline-contributors', days, type, limit],
    queryFn: () => api.getPRPipelineContributors(days, type, limit),
  })
}

export const usePRPipelineTrends = (days?: number) => {
  return useQuery({
    queryKey: ['pr-pipeline-trends', days],
    queryFn: () => api.getPRPipelineTrends(days),
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
    mutationFn: api.syncPRPipeline,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pr-pipeline'] })
    },
  })
}

export const usePRPipelineHistoricalSync = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: api.historicalSyncPRPipeline,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pr-pipeline'] })
    },
  })
}
