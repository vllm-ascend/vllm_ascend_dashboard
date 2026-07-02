// 模型管理相关类型定义

export interface ModelConfig {
  id: number
  model_name: string
  series?: string | null  // Qwen, Llama, DeepSeek, Other
  config_yaml?: string | null
  status: string  // active, inactive
  key_metrics_config?: Record<string, any> | null
  pass_threshold?: Record<string, any> | null
  startup_commands?: Record<string, string> | null
  official_doc_url?: string | null  // 官方文档链接
  created_at: string
  updated_at: string
}

export interface ModelReport {
  id: number
  model_config_id: number
  workflow_run_id?: number | null
  report_json?: Record<string, any> | null
  report_markdown?: string | null
  pass_fail?: string | null  // pass, fail
  auto_pass_fail?: string | null
  manual_override: boolean
  metrics_json?: Record<string, any> | null
  vllm_version?: string | null
  hardware?: string | null
  created_at: string

  // 新模板字段
  dtype?: string | null  // 权重类型：w8a8, fp16 等
  features?: string[] | null  // 特性列表
  serve_cmd?: Record<string, any> | null  // 启动命令：{mix: "..."} 或 {pd: {...}}
  environment?: Record<string, any> | null  // 环境变量
  tasks?: TaskReport[] | null  // 完整的 tasks 数组
}

export interface TaskReport {
  name: string
  metrics: Record<string, any>
  test_input?: Record<string, any>
  target?: Record<string, any>
  pass_fail?: string | null
}

export interface ModelTrendData {
  date: string
  datetime?: string
  report_id: number
  pass_fail?: string | null
  metrics: Record<string, any>
  vllm_version?: string | null
  hardware?: string | null
  tasks?: Array<{  // 新增：task 数据
    name: string
    metrics: Record<string, any>
  }>
}

export interface ModelComparisonData {
  id: number
  model_config_id: number
  model_name: string
  date: string
  pass_fail?: string | null
  auto_pass_fail?: string | null
  metrics: Record<string, any>
  vllm_version?: string | null
  hardware?: string | null
  workflow_run_id?: number | null
}

export interface ModelComparisonResponse {
  reports: ModelReport[]
  metrics_comparison: Record<string, Record<string, any>>
  changes: Record<string, {
    baseline: any
    current: any
    absolute_change: number | null
    percent_change: number | null
  }>
  tasks_comparison?: Array<{
    name: string
    baseline: {
      metrics: Record<string, any>
      test_input?: Record<string, any>
      target?: Record<string, any>
      pass_fail?: string
    }
    current: {
      metrics: Record<string, any>
      test_input?: Record<string, any>
      target?: Record<string, any>
      pass_fail?: string
    }
    changes: Record<string, {
      baseline: any
      current: any
      absolute_change: number | null
      percent_change: number | null
    }>
    only_in_baseline?: boolean  // 仅在基准报告中
    only_in_current?: boolean   // 仅在当前报告中
    is_common?: boolean         // 两个报告都有
  }>
}

export interface ModelSyncConfig {
  id: number
  workflow_name: string
  workflow_file: string
  artifacts_pattern?: string | null
  file_patterns?: string[] | null
  branch?: string  // 分支名称过滤（如 "main", "zxy_fix_ci"）
  enabled: boolean
  last_sync_at?: string | null
  created_at: string
  updated_at: string
}

export interface ModelSyncConfigCreate {
  workflow_name: string
  workflow_file: string
  artifacts_pattern?: string | null
  file_patterns?: string[] | null
  branch?: string  // 分支名称过滤（如 "main", "zxy_fix_ci"）
  enabled?: boolean
}

export interface ModelSyncConfigUpdate {
  workflow_name?: string
  workflow_file?: string
  artifacts_pattern?: string | null
  file_patterns?: string[] | null
  branch?: string  // 分支名称过滤（如 "main", "zxy_fix_ci"）
  enabled?: boolean
}

// 请求参数类型
export interface ModelListParams {
  series?: string
  status?: string
  search?: string
}

export interface ModelReportListParams {
  limit?: number
  offset?: number
}

export interface ModelTrendParams {
  days?: number
  metric_keys?: string
}

// 启动命令相关类型
export interface StartupCommands {
  [version: string]: {
    [scenario: string]: {
      [hardware: string]: string
    }
  }
}

// 模型系列选项
export const MODEL_SERIES_OPTIONS = [
  { label: 'Qwen', value: 'Qwen' },
  { label: 'Llama', value: 'Llama' },
  { label: 'DeepSeek', value: 'DeepSeek' },
] as const

export type ModelSeries = typeof MODEL_SERIES_OPTIONS[number]['value']

// ============ 支持矩阵类型 ============

export interface SupportMatrixModel {
  id: number
  model_name: string
  display_name?: string | null
  series?: string | null
  model_type: string
  role: string
  tier?: string | null
  support_status: string
  weight_formats?: string[] | null
  supported_hardware?: string[] | null
  max_model_len?: string | null
  official_doc_url?: string | null
  note?: string | null
  features: Record<string, string>
  verified_features: Record<string, boolean>
  source?: string | null
  upstream_synced_at?: string | null
}

export interface FeatureColumn {
  key: string
  title: string
}

export interface SupportMatrixResponse {
  models: SupportMatrixModel[]
  feature_columns: FeatureColumn[]
  statistics: {
    total_models: number
    by_type: Record<string, number>
    by_status: Record<string, number>
    by_tier: Record<string, number>
  }
}

export interface FeatureCompatEntry {
  feature_a: string
  feature_b: string
  compatibility: string
  footnote?: string | null
}

export interface FeatureCompatResponse {
  features: string[]
  matrix: FeatureCompatEntry[]
  legend: Record<string, string>
  synced_at?: string | null
}

export interface GlobalFeature {
  feature: string
  status: string
  next_step: string
}

export interface GlobalFeaturesResponse {
  features: GlobalFeature[]
  updated_at?: string | null
}

export interface SyncStatus {
  last_sync_at?: string | null
  success?: boolean | null
  dry_run?: boolean
  models_synced?: number
  new_models?: any[]
  updated_models?: any[]
  features_synced?: number
  compat_pairs_synced?: number
  error?: string | null
}

export interface SyncResult {
  success: boolean
  dry_run?: boolean
  models_synced?: number
  new_models?: any[]
  updated_models?: any[]
  features_synced?: number
  compat_pairs_synced?: number
  error?: string
}
