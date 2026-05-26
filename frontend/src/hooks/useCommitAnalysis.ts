import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as api from '../services/commitAnalysis'

export const useCommitAnalysis = (project: string, sha: string) => {
  return useQuery({
    queryKey: ['commit-analysis', project, sha],
    queryFn: () => api.getCommitAnalysis(project, sha),
    enabled: !!project && !!sha,
  })
}

export const useCommitAnalysisBatch = (project: string, shas: string[]) => {
  return useQuery({
    queryKey: ['commit-analysis-batch', project, shas],
    queryFn: () => api.batchGetCommitAnalysis(project, shas),
    enabled: !!project && shas.length > 0,
  })
}

export const useClaimCommitAnalysis = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ project, sha }: { project: string; sha: string }) => api.claimCommitAnalysis(project, sha),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['commit-analysis', variables.project, variables.sha] })
      queryClient.invalidateQueries({ queryKey: ['commit-analysis-batch', variables.project] })
    },
  })
}

export const useAssignCommitAnalysis = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ project, sha, assignee }: { project: string; sha: string; assignee: string }) =>
      api.assignCommitAnalysis(project, sha, assignee),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['commit-analysis', variables.project, variables.sha] })
      queryClient.invalidateQueries({ queryKey: ['commit-analysis-batch', variables.project] })
    },
  })
}

export const useUpdateCommitAnalysis = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      project,
      sha,
      data,
    }: {
      project: string
      sha: string
      data: api.CommitAnalysisUpdate
    }) => api.updateCommitAnalysis(project, sha, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['commit-analysis', variables.project, variables.sha] })
      queryClient.invalidateQueries({ queryKey: ['commit-analysis-batch', variables.project] })
    },
  })
}
