/**
 * Project Dashboard API Service
 */
import api from './api'

export interface ReleaseInfo {
  version: string
  is_stable: boolean
  published_at: string
  docker_commands: Record<string, string>
}

export interface VllmVersionInfo {
  vllm_version: string
  vllm_commit: string
  updated_at: string
}

export interface ModelSupportEntry {
  model_name: string
  series: string
  support: 'supported' | 'experimental' | 'not_supported' | 'untested'
  note?: string | null
  doc_link?: string | null
  // Feature support flags
  weight_format?: string | null  // e.g., "Bfloat16/W8A8"
  kv_cache_type?: string | null  // e.g., "Bfloat16/Float16"
  supported_hardware?: string | null  // e.g., "A2/A3"
  chunked_prefill?: boolean | null
  automatic_prefix_cache?: boolean | null
  lora?: boolean | null
  speculative_decoding?: boolean | null
  async_scheduling?: boolean | null
  tensor_parallel?: boolean | null
  pipeline_parallel?: boolean | null
  expert_parallel?: boolean | null
  data_parallel?: boolean | null
  prefilled_decode_disaggregation?: boolean | null
  piecewise_aclgraph?: boolean | null
  fullgraph_aclgraph?: boolean | null
  max_model_len?: number | string | null
  mlp_weight_prefetch?: boolean | null
}

export interface FeatureColumn {
  key: string
  title: string
  width: number
  type: 'toggle' | 'multiSelect' | 'input'
  options?: string[]
  placeholder?: string
}

export interface ModelSupportMatrix {
  entries: ModelSupportEntry[]
  featureColumns?: FeatureColumn[]
  source_url: string
  updated_at: string
}

export interface StaleIssue {
  number: number
  title: string
  html_url: string
  created_at: string
  updated_at: string
  days_stale: number
  author: string | null
  labels: string[]
  type?: 'issue' | 'pr'
  draft?: boolean
  pr_state?: string
}

export interface CommitInfo {
  sha: string
  title: string
  message: string
  author: string
  date: string
  category: 'BugFix' | 'Feature' | 'Performance' | 'Refactor' | 'Doc' | 'Test' | 'CI' | 'Misc'
  pr_number: number | null
}

export interface TagComparisonResult {
  base_tag: string
  head_tag: string
  total_commits: number
  commits: CommitInfo[]
  summary: Record<string, number>
  bug_fixes: CommitInfo[]
  features: CommitInfo[]
  performance_improvements: CommitInfo[]
  refactors: CommitInfo[]
  docs: CommitInfo[]
  tests: CommitInfo[]
  ci_changes: CommitInfo[]
  misc: CommitInfo[]
}

export interface ProjectDashboardConfig {
  id: number
  config_key: string
  config_value: Record<string, any>
  description: string | null
  created_at: string
  updated_at: string
}

/**
 * Get all releases with docker commands
 */
export const getReleases = async (recommended_only: boolean = false) => {
  const response = await api.get<{ releases: ReleaseInfo[] }>('/project-dashboard/releases', {
    params: { recommended: recommended_only }
  })
  return response.data
}

/**
 * Get main branch vllm version info
 */
export const getMainVersions = async () => {
  const response = await api.get<VllmVersionInfo>('/project-dashboard/versions/main')
  return response.data
}

/**
 * Get model support matrix
 */
export const getModelSupportMatrix = async () => {
  const response = await api.get<ModelSupportMatrix>('/project-dashboard/model-support-matrix')
  return response.data
}

/**
 * Update model support matrix (admin only)
 */
export const updateModelSupportMatrix = async (data: { entries: ModelSupportEntry[], featureColumns?: FeatureColumn[] }) => {
  const response = await api.put<{ success: boolean; message: string }>('/project-dashboard/model-support-matrix', data)
  return response.data
}

/**
 * Get stale issues and PRs
 */
export const getStaleIssues = async (days: number = 7) => {
  const response = await api.get<{ 
    issues: StaleIssue[]
    prs: StaleIssue[]
    days_threshold: number 
  }>(
    '/project-dashboard/stale-issues',
    { params: { days } }
  )
  return response.data
}

export interface WorkflowRun {
  id: number
  name: string
  status: string
  conclusion: string | null
  html_url: string
  created_at: string
  updated_at: string
  details_url?: string
}

/**
 * Get PR CI status
 */
export const getPRCIStatus = async (prNumber: number) => {
  const response = await api.get<{
    pr_number: number
    pr_title: string
    pr_state: string
    pr_url: string
    workflow_runs: {
      in_progress: WorkflowRun[]
      queued: WorkflowRun[]
      completed: WorkflowRun[]
      failed: WorkflowRun[]
      success: WorkflowRun[]
      skipped: WorkflowRun[]
    }
    summary: Record<string, number>
  }>(`/project-dashboard/pr/${prNumber}/ci-status`)
  return response.data
}

/**
 * Rerun CI for a PR (requires login)
 */
export const rerunPRCI = async (prNumber: number, workflowId?: number) => {
  const response = await api.post<{ success: boolean; message: string; pr_number: number; workflow_id?: number }>(
    `/project-dashboard/pr/${prNumber}/rerun-ci`,
    { pr_number: prNumber, workflow_id: workflowId }
  )
  return response.data
}

/**
 * Force merge a PR (admin only)
 */
export const forceMergePR = async (prNumber: number) => {
  const response = await api.post<{ success: boolean; message: string; pr_number: number; merge_sha?: string }>(
    `/project-dashboard/pr/${prNumber}/force-merge`
  )
  return response.data
}

/**
 * Compare two tags
 */
export const compareTags = async (baseTag: string, headTag: string) => {
  const response = await api.post<TagComparisonResult>('/project-dashboard/compare-tags', {
    base_tag: baseTag,
    head_tag: headTag,
  })
  return response.data
}

/**
 * Get all dashboard configs (admin only)
 */
export const getDashboardConfig = async () => {
  const response = await api.get<{ configs: ProjectDashboardConfig[] }>('/project-dashboard/config')
  return response.data
}

/**
 * Update dashboard config (admin only)
 */
export const updateDashboardConfig = async (
  configKey: string,
  configValue: Record<string, any>,
  description?: string
) => {
  const response = await api.put<{ success: boolean; message: string; config: ProjectDashboardConfig }>(
    `/project-dashboard/config/${configKey}`,
    { config_value: configValue, description }
  )
  return response.data
}

/**
 * Update local git cache (admin only)
 */
export const updateLocalCache = async () => {
  const response = await api.post<{ success: boolean; message: string }>('/project-dashboard/cache/update')
  return response.data
}

/**
 * Rebuild local git cache (admin only) - deletes and reclones repo
 */
export const rebuildLocalCache = async () => {
  const response = await api.post<{ success: boolean; message: string }>('/project-dashboard/cache/rebuild')
  return response.data
}

/**
 * Fix local git cache (admin only) - cleans up locks and resets state without reclone
 */
export const fixLocalCache = async () => {
  const response = await api.post<{ success: boolean; message: string }>('/project-dashboard/cache/fix')
  return response.data
}

/**
 * Get force merge PR records
 */
export const getForceMergeRecords = async () => {
  const response = await api.get<{ records: Array<{
    pr_number: number
    pr_title: string
    merged_by_user_id: number
    merged_by_username: string
    merged_at: string
    merge_sha: string
  }> }>('/project-dashboard/force-merge-records')
  return response.data
}

// ==================== 版本质量评估报告 ====================

export interface VersionQualityReportMeta {
  report_id: string
  base_tag: string
  head_tag: string
  generated_at: string
  html_length: number
  llm_provider?: string | null
  llm_model?: string | null
  prompt_tokens?: number | null
  completion_tokens?: number | null
  generation_time_seconds?: number | null
  total_commits: number
  open_bugs: number
  merged_prs: number
  ci_success_rate?: number | null
  stars?: number | null
  forks?: number | null
  data_sources: string[]
}

export interface VersionQualityReportHtml {
  html: string
  meta: VersionQualityReportMeta
}

/**
 * 生成版本质量评估报告（管理员）
 */
export const generateVersionQualityReport = async (
  baseTag: string,
  headTag: string,
  forceRegenerate: boolean = false
) => {
  const response = await api.post<{ success: boolean; report: VersionQualityReportMeta }>(
    '/project-dashboard/version-quality-report/generate',
    { base_tag: baseTag, head_tag: headTag, force_regenerate: forceRegenerate }
  )
  return response.data
}

/**
 * 获取版本质量评估报告列表
 */
export const listVersionQualityReports = async () => {
  const response = await api.get<{ reports: VersionQualityReportMeta[] }>(
    '/project-dashboard/version-quality-report/list'
  )
  return response.data
}

/**
 * 获取单个报告元数据
 */
export const getVersionQualityReport = async (reportId: string) => {
  const response = await api.get<VersionQualityReportMeta>(
    `/project-dashboard/version-quality-report/${reportId}`
  )
  return response.data
}

/**
 * 获取报告 HTML 内容（用于前端预览）
 */
export const getVersionQualityReportHtml = async (reportId: string) => {
  const response = await api.get<VersionQualityReportHtml>(
    `/project-dashboard/version-quality-report/${reportId}/html`
  )
  return response.data
}

/**
 * 获取报告下载 URL
 */
export const getVersionQualityReportDownloadUrl = (reportId: string) => {
  return `/api/v1/project-dashboard/version-quality-report/${reportId}/download`
}

/**
 * 删除版本质量评估报告（管理员）
 */
export const deleteVersionQualityReport = async (reportId: string) => {
  const response = await api.delete<{ success: boolean; message: string }>(
    `/project-dashboard/version-quality-report/${reportId}`
  )
  return response.data
}
