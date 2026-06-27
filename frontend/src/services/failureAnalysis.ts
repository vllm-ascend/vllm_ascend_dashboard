import api, { longTimeoutApiClient } from './api'

export interface FailureAnalysis {
  id: number
  job_id: number
  run_id: number
  workflow_name: string
  job_name: string
  failure_date: string
  failure_fingerprint: string | null
  reused_analysis_id: number | null
  problem_category: string | null
  root_cause_summary: string | null
  improvement_measures_summary: string | null
  report_file_path: string | null
  llm_provider: string | null
  llm_model: string | null
  prompt_tokens: number | null
  completion_tokens: number | null
  generation_time_seconds: number | null
  analysis_status: string
  error_message: string | null
  triggered_by: string | null
  share_token: string | null
  created_at: string | null
  updated_at: string | null
}

export interface FailureAnalysisListResponse {
  total: number
  items: FailureAnalysis[]
}

export const listFailureAnalyses = async (params?: {
  problem_category?: string
  analysis_status?: string
  workflow_name?: string
  days_back?: number
}): Promise<FailureAnalysisListResponse> => {
  const response = await api.get<FailureAnalysisListResponse>('/ci/failure-analysis/list', { params })
  return response.data
}

export const getFailureAnalysis = async (analysisId: number): Promise<FailureAnalysis> => {
  const response = await api.get<FailureAnalysis>(`/ci/failure-analysis/${analysisId}`)
  return response.data
}

export const getFailureAnalysisReport = async (analysisId: number): Promise<{ content: string; analysis_id: number }> => {
  const response = await api.get<{ content: string; analysis_id: number }>(`/ci/failure-analysis/${analysisId}/report`)
  return response.data
}

export const getJobFailureAnalysis = async (jobId: number): Promise<FailureAnalysis | null> => {
  const response = await api.get<FailureAnalysis | null>(`/ci/jobs/${jobId}/failure-analysis`)
  return response.data
}

export const analyzeFailedJob = async (jobId: number, force: boolean = false): Promise<FailureAnalysis> => {
  const response = await longTimeoutApiClient.post<FailureAnalysis>(`/ci/failure-analysis/analyze/${jobId}`, null, {
    params: { force },
  })
  return response.data
}

export const analyzeBatch = async (daysBack: number = 7): Promise<{ success: boolean; message: string; count: number }> => {
  const response = await longTimeoutApiClient.post<{ success: boolean; message: string; count: number }>('/ci/failure-analysis/analyze-batch', null, {
    params: { days_back: daysBack },
  })
  return response.data
}

export const PROBLEM_CATEGORY_MAP: Record<string, { color: string; label: string }> = {
  '基础设施': { color: '#faad14', label: '基础设施' },
  '测试用例': { color: '#1890ff', label: '测试用例' },
  '开发代码': { color: '#ff4d4f', label: '开发代码' },
  '其他': { color: '#64748b', label: '其他' },
}

export const ANALYSIS_STATUS_MAP: Record<string, { color: string; label: string }> = {
  pending: { color: '#64748b', label: '待分析' },
  analyzing: { color: '#1890ff', label: '分析中' },
  completed: { color: '#15be53', label: '已完成' },
  reused: { color: '#8c8c8c', label: '复用分析' },
  failed: { color: '#ff4d4f', label: '分析失败' },
}
