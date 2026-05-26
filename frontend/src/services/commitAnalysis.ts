import apiClient from './api'

export const CHANGE_TYPES = ['Feature', 'Bugfix', 'Refactor', 'Common', 'Test', 'CI', 'Other'] as const
export const ANALYSIS_STATUSES = ['未分析', '已分析', '已闭环'] as const

export type CommitChangeType = typeof CHANGE_TYPES[number]
export type CommitAnalysisStatus = typeof ANALYSIS_STATUSES[number]

export interface CommitAnalysis {
  project: string
  sha: string
  assignee: string | null
  what_commit_did: string | null
  change_type: CommitChangeType | null
  affects_api: boolean | null
  vllm_ascend_impact: string | null
  next_plan: string | null
  planned_closure_time: string | null
  actual_closure_time: string | null
  created_at: string | null
  created_by: string | null
  updated_at: string | null
  updated_by: string | null
  status: CommitAnalysisStatus
  can_edit: boolean
}

export interface CommitAnalysisUpdate {
  what_commit_did?: string | null
  change_type?: CommitChangeType | null
  affects_api?: boolean | null
  vllm_ascend_impact?: string | null
  next_plan?: string | null
  planned_closure_time?: string | null
  actual_closure_time?: string | null
}

export interface CommitAnalysisBatchItem {
  sha: string
  assignee: string | null
  change_type: CommitChangeType | null
  status: CommitAnalysisStatus
}

export interface CommitAnalysisBatchResponse {
  project: string
  analyses: Record<string, CommitAnalysisBatchItem>
  filters: {
    assignees: string[]
    change_types: CommitChangeType[]
    statuses: CommitAnalysisStatus[]
  }
}

export const getCommitAnalysis = async (project: string, sha: string): Promise<CommitAnalysis> => {
  const response = await apiClient.get(`/commit-analysis/${project}/${sha}`)
  return response.data
}

export const batchGetCommitAnalysis = async (project: string, shas: string[]): Promise<CommitAnalysisBatchResponse> => {
  const response = await apiClient.post(`/commit-analysis/${project}/batch`, { shas })
  return response.data
}

export const claimCommitAnalysis = async (project: string, sha: string): Promise<CommitAnalysis> => {
  const response = await apiClient.post(`/commit-analysis/${project}/${sha}/claim`)
  return response.data
}

export const assignCommitAnalysis = async (project: string, sha: string, assignee: string): Promise<CommitAnalysis> => {
  const response = await apiClient.post(`/commit-analysis/${project}/${sha}/assign`, { assignee })
  return response.data
}

export const updateCommitAnalysis = async (
  project: string,
  sha: string,
  data: CommitAnalysisUpdate
): Promise<CommitAnalysis> => {
  const response = await apiClient.put(`/commit-analysis/${project}/${sha}`, data)
  return response.data
}
