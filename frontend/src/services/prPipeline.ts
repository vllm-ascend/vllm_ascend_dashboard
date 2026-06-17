import api from './api'

export interface PullRequestResponse {
  id: number
  pr_number: number
  owner: string
  repo: string
  title: string
  author: string
  author_avatar_url: string | null
  html_url: string | null
  state: string
  is_draft: boolean
  labels: string[]
  head_branch: string | null
  head_sha: string | null
  base_branch: string | null
  additions: number
  deletions: number
  changed_files: number
  pipeline_stage: string | null
  review_status: string | null
  reviewers: { login: string; avatar_url: string; state: string }[]
  ci_status: string | null
  ci_workflow_run_id: number | null
  first_review_at: string | null
  first_approved_at: string | null
  ci_started_at: string | null
  ci_completed_at: string | null
  merged_at: string | null
  closed_at: string | null
  created_at: string
  updated_at: string | null
  data: any | null
  time_to_first_review_hours: number | null
  time_to_merge_hours: number | null
  time_to_ci_hours: number | null
  ci_duration_hours: number | null
  time_to_approval_hours: number | null
}

export interface PRPipelineOverview {
  open_count: number
  merged_count: number
  closed_count: number
  draft_count: number
  backlog_index: number
  backlog_level: string
  merge_rate: number
  avg_time_to_first_review_hours: number | null
  avg_time_to_merge_hours: number | null
  pipeline_stage_distribution: {
    submitted: number
    reviewing: number
    approved: number
    ci_running: number
    ci_passed: number
    ci_failed: number
    merging: number
    merged: number
    closed: number
  }
  recent_opened_count: number
  recent_merged_count: number
  last_sync_at: string | null
}

export interface PRPipelinePercentileMetric {
  p50: number | null
  p90: number | null
  avg: number | null
  count: number
}

export interface PRPipelineMetrics {
  first_response_hours: PRPipelinePercentileMetric
  review_to_approval_hours: PRPipelinePercentileMetric
  ci_duration_hours: PRPipelinePercentileMetric
  merge_hours: PRPipelinePercentileMetric
  total_cycle_hours: PRPipelinePercentileMetric
  merge_rate: number
  backlog_index: number
  survival_distribution: {
    day: number
    hours_threshold: number
    cumulative_percent: number
    count: number
  }[]
}

export interface PRPipelineContributor {
  username: string
  avatar_url: string | null
  type: string
  pr_count: number
  review_count: number
  lines_added: number
  lines_removed: number
  avg_first_response_hours: number | null
  merged_count: number
}

export interface PRPipelineKanban {
  submitted: PullRequestResponse[]
  reviewing: PullRequestResponse[]
  approved: PullRequestResponse[]
  ci_running: PullRequestResponse[]
  ci_passed: PullRequestResponse[]
  ci_failed: PullRequestResponse[]
  merging: PullRequestResponse[]
  merged: PullRequestResponse[]
  closed: PullRequestResponse[]
}

export interface PRPipelineListResponse {
  total: number
  items: PullRequestResponse[]
  page: number
  page_size: number
}

export interface PRPipelineTrendPoint {
  date: string
  opened: number
  merged: number
  closed: number
  open_total: number
}

export interface PRPipelineTrendsResponse {
  trends: PRPipelineTrendPoint[]
  period_days: number
}

export const getOverview = async (days?: number): Promise<PRPipelineOverview> => {
  const response = await api.get<PRPipelineOverview>('/pr-pipeline/overview', { params: { days } })
  return response.data
}

export const getKanban = async (
  state?: string,
  includeDraft?: boolean,
  limitPerStage?: number
): Promise<PRPipelineKanban> => {
  const response = await api.get<PRPipelineKanban>('/pr-pipeline/kanban', {
    params: { state, include_draft: includeDraft, limit_per_stage: limitPerStage },
  })
  return response.data
}

export const getList = async (params?: {
  state?: string
  pipeline_stage?: string
  author?: string
  reviewer?: string
  is_draft?: boolean
  label?: string
  search?: string
  sort_by?: string
  sort_order?: string
  page?: number
  page_size?: number
}): Promise<PRPipelineListResponse> => {
  const response = await api.get<PRPipelineListResponse>('/pr-pipeline/list', { params })
  return response.data
}

export const getMetrics = async (days?: number): Promise<PRPipelineMetrics> => {
  const response = await api.get<PRPipelineMetrics>('/pr-pipeline/metrics', { params: { days } })
  return response.data
}

export const getContributors = async (
  days?: number,
  type?: string,
  limit?: number
): Promise<PRPipelineContributor[]> => {
  const response = await api.get<PRPipelineContributor[]>('/pr-pipeline/contributors', {
    params: { days, type, limit },
  })
  return response.data
}

export const getTrends = async (days?: number): Promise<PRPipelineTrendsResponse> => {
  const response = await api.get<PRPipelineTrendsResponse>('/pr-pipeline/trends', { params: { days } })
  return response.data
}

export const syncPRPipeline = async (daysBack?: number): Promise<{ message: string }> => {
  const response = await api.post<{ message: string }>('/pr-pipeline/sync', null, {
    params: { days_back: daysBack },
  })
  return response.data
}

export const historicalSyncPRPipeline = async (
  phases?: string[],
  monthsBack?: number
): Promise<{ message: string }> => {
  const response = await api.post<{ message: string }>('/pr-pipeline/historical-sync', {
    phases,
    months_back: monthsBack,
  })
  return response.data
}

export const getPRDetail = async (prNumber: number): Promise<PullRequestResponse> => {
  const response = await api.get<PullRequestResponse>(`/pr-pipeline/${prNumber}`)
  return response.data
}
