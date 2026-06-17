import api from './api'

// ============ Types ============

export interface CIResult {
  id: number
  workflow_name: string
  run_id: number
  run_number?: number
  job_name: string | null
  status: string
  conclusion: string | null
  event?: string | null
  branch?: string | null
  head_sha?: string | null
  hardware: string | null
  started_at: string | null
  completed_at: string | null
  duration_seconds: number | null
  created_at: string
  github_html_url?: string
}

export interface CIJob {
  id: number
  job_id: number
  run_id: number
  workflow_name: string
  job_name: string
  status: string
  conclusion: string | null
  hardware: string | null
  runner_name: string | null
  started_at: string | null
  completed_at: string | null
  duration_seconds: number | null
  runner_labels?: string[]
  steps_summary?: StepSummary[]
  steps_data?: StepSummary[]
  created_at: string
  github_job_url?: string
}

export interface StepSummary {
  name: string
  status: string
  conclusion: string | null
  number: number
}

export interface CIStats {
  total_runs: number
  success_rate: number
  avg_duration_seconds: number | null
  last_7_days: {
    runs: number
    success_rate: number
    avg_duration_seconds: number | null
  } | null
}

export interface CITrend {
  date: string
  total_runs: number
  success_runs: number
  success_rate: number
  avg_duration_seconds: number | null
}

export interface CISyncResponse {
  success: boolean
  message: string
  collected_count?: number
}

export interface SyncStatus {
  scheduler_running: boolean
  jobs: Array<{
    id: string
    name: string
    next_run_time: string | null
  }>
  error?: string
}

export interface SyncProgress {
  status: string
  progress_percentage: number
  total_workflows: number
  completed_workflows: number
  current_workflow: string | null
  total_collected: number
  workflow_details: Record<string, {
    collected: number
    status: string
    updated_at: string
  }>
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  elapsed_seconds: number | null
}

// ============ API Functions ============

/**
 * 获取 workflow 列表
 */
export const getWorkflows = async (): Promise<string[]> => {
  const response = await api.get<string[]>('/ci/workflows')
  return response.data
}

/**
 * 获取 CI 运行列表
 */
export const getRuns = async (params?: {
  workflow_name?: string
  status?: string
  hardware?: string
  limit?: number
}): Promise<CIResult[]> => {
  const response = await api.get<CIResult[]>('/ci/runs', { params })
  return response.data
}

/**
 * 获取 CI 统计数据
 */
export const getStats = async (params?: {
  workflow_name?: string
  hardware?: string
}): Promise<CIStats> => {
  const response = await api.get<CIStats>('/ci/stats', { params })
  return response.data
}

/**
 * 获取 CI 趋势数据
 */
export const getTrends = async (params: {
  days?: number
  workflow_name?: string
  hardware?: string
}): Promise<CITrend[]> => {
  const response = await api.get<CITrend[]>('/ci/trends', { params })
  return response.data
}

/**
 * 获取指定 workflow run 的所有 jobs
 */
export const getJobsByRun = async (runId: number): Promise<CIJob[]> => {
  const response = await api.get<CIJob[]>(`/ci/runs/${runId}/jobs`)
  return response.data
}

/**
 * 获取 job 详情
 */
export const getJobDetail = async (jobId: number): Promise<CIJob> => {
  const response = await api.get<CIJob>(`/ci/jobs/${jobId}`)
  return response.data
}

/**
 * 手动触发数据同步
 */
export const triggerSync = async (): Promise<CISyncResponse> => {
  const response = await api.post<CISyncResponse>('/ci/sync')
  return response.data
}

/**
 * 获取同步任务状态
 */
export const getSyncStatus = async (): Promise<SyncStatus> => {
  const response = await api.get<SyncStatus>('/ci/sync/status')
  return response.data
}

/**
 * 获取同步进度详情
 */
export const getSyncProgress = async (): Promise<SyncProgress> => {
  const response = await api.get<SyncProgress>('/ci/sync/progress')
  return response.data
}
