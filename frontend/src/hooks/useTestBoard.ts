import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as testBoardApi from '../services/testBoard'

export const useTestOverview = (days: number = 7, enabled = true) => {
  return useQuery({
    queryKey: ['test-board-overview', days],
    queryFn: () => testBoardApi.getOverview(days),
    enabled,
  })
}

export const useTestSuites = (enabled = true) => {
  return useQuery({
    queryKey: ['test-board-suites'],
    queryFn: testBoardApi.getSuites,
    enabled,
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
  include_stale?: boolean
  page?: number
  per_page?: number
}, enabled = true) => {
  return useQuery({
    queryKey: ['test-board-cases', params],
    queryFn: () => testBoardApi.getCases(params),
    enabled,
  })
}

export const useCaseDetail = (caseId: number | null) => {
  return useQuery({
    queryKey: ['test-board-case-detail', caseId],
    queryFn: () => caseId ? testBoardApi.getCaseDetail(caseId) : Promise.resolve(null),
    enabled: !!caseId,
  })
}

export const useFilterOptions = (enabled = true) => {
  return useQuery({
    queryKey: ['test-board-filter-options'],
    queryFn: () => testBoardApi.getFilterOptions(),
    enabled,
  })
}

export const useTestRuns = (params?: {
  test_case_id?: number
  ci_run_id?: number
  workflow_name?: string
  result?: string
  search?: string
  days?: number
  page?: number
  per_page?: number
}, enabled = true) => {
  return useQuery({
    queryKey: ['test-board-runs', params],
    queryFn: () => testBoardApi.getRuns(params),
    enabled,
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
}, enabled = true) => {
  return useQuery({
    queryKey: ['test-board-flaky', params],
    queryFn: () => testBoardApi.getFlakyCases(params),
    enabled,
  })
}

export const useFailureBreakdown = (params?: {
  days?: number
  category?: string
  suite_name?: string
}, enabled = true) => {
  return useQuery({
    queryKey: ['test-board-failures', params],
    queryFn: () => testBoardApi.getFailureBreakdown(params),
    enabled,
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

export const useOwnerMatrix = (enabled = true) => {
  return useQuery({
    queryKey: ['test-board-owners'],
    queryFn: testBoardApi.getOwnerMatrix,
    enabled,
  })
}

export const useModuleHealth = (enabled = true) => {
  return useQuery({
    queryKey: ['test-board-modules'],
    queryFn: testBoardApi.getModuleHealth,
    enabled,
  })
}

export const useTestCaseFeatureMatrix = () => {
  return useQuery({
    queryKey: ['test-board-case-matrix'],
    queryFn: testBoardApi.getCaseFeatureMatrix,
  })
}

export const useTestTrends = (days: number = 30) => {
  return useQuery({
    queryKey: ['test-board-trends', days],
    queryFn: () => testBoardApi.getTrends(days),
  })
}

export const useCoverageBreadth = (params?: {
  page?: number
  per_page?: number
  module?: string
  sort?: string
  order?: string
}) => {
  return useQuery({
    queryKey: ['test-board-coverage-breadth', params],
    queryFn: () => testBoardApi.getCoverageBreadth(params),
    refetchInterval: 600000,
  })
}

export const useCoverageLines = (params?: {
  page?: number
  per_page?: number
  sort?: string
  order?: string
}) => {
  return useQuery({
    queryKey: ['test-board-coverage-lines', params],
    queryFn: () => testBoardApi.getCoverageLines(params),
    refetchInterval: 600000,
  })
}

export const useE2ECoverage = (enabled = true) => {
  return useQuery({
    queryKey: ['test-board-coverage-e2e'],
    queryFn: testBoardApi.getE2ECoverage,
    enabled,
    refetchInterval: 600000,
  })
}

export const useCoverageSyncStatus = () => {
  return useQuery({
    queryKey: ['test-board-coverage-status'],
    queryFn: testBoardApi.getCoverageSyncStatus,
    refetchInterval: 600000,
  })
}

export const useTriggerCoverageSync = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (source: string) => testBoardApi.triggerCoverageSync(source),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['test-board-coverage'] })
    },
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

export const useUpdateCase = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ caseId, payload }: { caseId: number; payload: testBoardApi.TestCaseUpdatePayload }) =>
      testBoardApi.updateCase(caseId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['test-board-cases'] })
      queryClient.invalidateQueries({ queryKey: ['test-board-overview'] })
      queryClient.invalidateQueries({ queryKey: ['test-board-flaky'] })
    },
  })
}

// ---------------------------------------------------------------------------
