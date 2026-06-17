import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as faApi from '../services/failureAnalysis'

export const useFailureAnalysisList = (params?: {
  problem_category?: string
  analysis_status?: string
  workflow_name?: string
  days_back?: number
}) => {
  return useQuery({
    queryKey: ['failure-analysis-list', params],
    queryFn: () => faApi.listFailureAnalyses(params),
  })
}

export const useFailureAnalysis = (analysisId: number | null) => {
  return useQuery({
    queryKey: ['failure-analysis', analysisId],
    queryFn: () => analysisId ? faApi.getFailureAnalysis(analysisId) : Promise.resolve(null),
    enabled: !!analysisId,
  })
}

export const useFailureAnalysisReport = (analysisId: number | null) => {
  return useQuery({
    queryKey: ['failure-analysis-report', analysisId],
    queryFn: () => analysisId ? faApi.getFailureAnalysisReport(analysisId) : Promise.resolve(null),
    enabled: !!analysisId,
  })
}

export const useJobFailureAnalysis = (jobId: number | null) => {
  return useQuery({
    queryKey: ['job-failure-analysis', jobId],
    queryFn: () => jobId ? faApi.getJobFailureAnalysis(jobId) : Promise.resolve(null),
    enabled: !!jobId,
  })
}

export const useAnalyzeFailedJob = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ jobId, force = false }: { jobId: number; force?: boolean }) =>
      faApi.analyzeFailedJob(jobId, force),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['failure-analysis-list'] })
      queryClient.invalidateQueries({ queryKey: ['job-failure-analysis'] })
      queryClient.invalidateQueries({ queryKey: ['failure-analysis'] })
      queryClient.invalidateQueries({ queryKey: ['failure-analysis-report'] })
    },
  })
}

export const useAnalyzeBatch = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ daysBack = 7 }: { daysBack?: number }) =>
      faApi.analyzeBatch(daysBack),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['failure-analysis-list'] })
      queryClient.invalidateQueries({ queryKey: ['job-failure-analysis'] })
    },
  })
}
