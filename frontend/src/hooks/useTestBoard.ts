import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as testBoardApi from '../services/testBoard'

export const useTestOverview = (days: number = 7) => {
  return useQuery({
    queryKey: ['test-board-overview', days],
    queryFn: () => testBoardApi.getOverview(days),
  })
}

export const useTestSuites = () => {
  return useQuery({
    queryKey: ['test-board-suites'],
    queryFn: testBoardApi.getSuites,
  })
}

export const useTestCases = (params?: {
  test_type?: string
  suite_name?: string
  module_name?: string
  hardware?: string
  result?: string
  health_level?: string
  is_flaky?: boolean
  owner?: string
  sort?: string
  order?: string
  page?: number
  per_page?: number
}) => {
  return useQuery({
    queryKey: ['test-board-cases', params],
    queryFn: () => testBoardApi.getCases(params),
  })
}

export const useCaseDetail = (caseId: number | null) => {
  return useQuery({
    queryKey: ['test-board-case-detail', caseId],
    queryFn: () => caseId ? testBoardApi.getCaseDetail(caseId) : Promise.resolve(null),
    enabled: !!caseId,
  })
}

export const useFilterOptions = () => {
  return useQuery({
    queryKey: ['test-board-filter-options'],
    queryFn: () => testBoardApi.getFilterOptions(),
  })
}

export const useTestRuns = (params?: {
  test_case_id?: number
  result?: string
  days?: number
  page?: number
  per_page?: number
}) => {
  return useQuery({
    queryKey: ['test-board-runs', params],
    queryFn: () => testBoardApi.getRuns(params),
  })
}

export const useFlakyCases = (params?: {
  min_flip_rate?: number
  days?: number
  suite_name?: string
  module_name?: string
  sort?: string
  page?: number
  per_page?: number
}) => {
  return useQuery({
    queryKey: ['test-board-flaky', params],
    queryFn: () => testBoardApi.getFlakyCases(params),
  })
}

export const useFailureBreakdown = (params?: {
  days?: number
  category?: string
  suite_name?: string
}) => {
  return useQuery({
    queryKey: ['test-board-failures', params],
    queryFn: () => testBoardApi.getFailureBreakdown(params),
  })
}

export const useDurationAnalysis = (params?: {
  days?: number
  suite_name?: string
}) => {
  return useQuery({
    queryKey: ['test-board-duration', params],
    queryFn: () => testBoardApi.getDurationAnalysis(params),
  })
}

export const useOwnerMatrix = () => {
  return useQuery({
    queryKey: ['test-board-owners'],
    queryFn: testBoardApi.getOwnerMatrix,
  })
}

export const useModuleHealth = () => {
  return useQuery({
    queryKey: ['test-board-modules'],
    queryFn: testBoardApi.getModuleHealth,
  })
}

export const useTestTrends = (days: number = 30) => {
  return useQuery({
    queryKey: ['test-board-trends', days],
    queryFn: () => testBoardApi.getTrends(days),
  })
}

export const useTriggerSync = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: testBoardApi.triggerSync,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['test-board'] })
    },
  })
}

export const useAnnotateFailure = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: testBoardApi.annotateFailure,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['test-board-runs'] })
    },
  })
}
