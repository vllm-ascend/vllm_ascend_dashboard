import api from './api'

export interface CodeMetricsOverview {
  has_data: boolean
  message?: string
  snapshot_date?: string
  collection_status?: string
  health_score?: number
  health_scores?: {
    complexity: number
    security: number
    duplication: number
    method_size: number
    tech_debt: number
    lint: number
  }
  metrics?: {
    total_loc: number
    total_functions: number
    total_files: number
    cc_per_method: number
    cc_maximum: number
    cc_huge_count: number
    dup_ratio: number
    dup_blocks: number
    unsafe_functions_count: number
    lint_errors: number
    todo_count: number
    fixme_count: number
  }
  language_loc?: Record<string, number>
  module_loc?: Record<string, number>
}

export interface ComplexityItem {
  file_path: string
  function_name: string
  language: string | null
  cyclomatic_complexity: number | null
  max_nesting_depth: number | null
  function_lines: number | null
}

export interface DuplicationItem {
  file_a: string
  file_b: string
  lines: number
  fragment: string | null
}

export interface HeatmapItem {
  file_path: string
  change_count: number
  bug_fix_count: number
  last_changed: string | null
}

export interface TrendItem {
  date: string
  total_loc: number
  total_functions: number
  cc_per_method: number
  cc_huge_count: number
  dup_ratio: number
  health_score: number
  lint_errors: number
  todo_count: number
}

export async function getOverview(days?: number): Promise<CodeMetricsOverview> {
  const { data } = await api.get('/code-metrics/overview', { params: { days } })
  return data
}

export async function getComplexity(limit?: number): Promise<{ items: ComplexityItem[] }> {
  const { data } = await api.get('/code-metrics/complexity', { params: { limit } })
  return data
}

export async function getDuplication(limit?: number): Promise<{ items: DuplicationItem[] }> {
  const { data } = await api.get('/code-metrics/duplication', { params: { limit } })
  return data
}

export async function getHeatmap(limit?: number): Promise<{ items: HeatmapItem[] }> {
  const { data } = await api.get('/code-metrics/heatmap', { params: { limit } })
  return data
}

export async function getTrends(days?: number): Promise<{ items: TrendItem[] }> {
  const { data } = await api.get('/code-metrics/trends', { params: { days } })
  return data
}
