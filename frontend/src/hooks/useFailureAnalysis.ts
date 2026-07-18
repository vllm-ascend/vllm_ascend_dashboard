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
    refetchInterval: (query) => {
      const data = query.state.data as { items?: Array<{ analysis_status?: string }> } | undefined
      // The analysis POST returns immediately while work continues in the
      // backend. Keep the workflow table fresh until every active item exits.
      return data?.items?.some(item => item.analysis_status === 'analyzing')
        ? 5000
        : false
    },
    refetchOnWindowFocus: true,
  })
}

export const useFailureAnalysis = (analysisId: number | null) => {
  return useQuery({
    queryKey: ['failure-analysis', analysisId],
    queryFn: () => analysisId ? faApi.getFailureAnalysis(analysisId) : Promise.resolve(null),
    enabled: !!analysisId,
    refetchInterval: (query) => {
      const data = query.state.data as { analysis_status?: string } | null
      // 分析进行中时每 5 秒轮询一次，完成后停止
      if (data?.analysis_status === 'analyzing') return 5000
      return false
    },
  })
}

export const useFailureAnalysisReport = (analysisId: number | null) => {
  return useQuery({
    queryKey: ['failure-analysis-report', analysisId],
    queryFn: () => analysisId ? faApi.getFailureAnalysisReport(analysisId) : Promise.resolve(null),
    enabled: !!analysisId,
  })
}

export const useFailureAnalysisKnowledgeGraph = (analysisId: number | null) => {
  return useQuery({
    queryKey: ['failure-analysis-knowledge-graph', analysisId],
    queryFn: () => analysisId ? faApi.getFailureAnalysisKnowledgeGraph(analysisId) : Promise.resolve(null),
    enabled: !!analysisId,
  })
}

export const useJobFailureAnalysis = (jobId: number | null) => {
  return useQuery({
    queryKey: ['job-failure-analysis', jobId],
    queryFn: () => jobId ? faApi.getJobFailureAnalysis(jobId) : Promise.resolve(null),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const data = query.state.data as { analysis_status?: string } | null
      if (data?.analysis_status === 'analyzing') return 5000
      return false
    },
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

export const useCancelAnalysis = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (jobId: number) => faApi.cancelAnalysis(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['failure-analysis-list'] })
      queryClient.invalidateQueries({ queryKey: ['job-failure-analysis'] })
      queryClient.invalidateQueries({ queryKey: ['failure-analysis'] })
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
