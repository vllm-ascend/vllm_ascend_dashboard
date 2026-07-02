import api from './api'
import type {
  ModelConfig,
  ModelReport,
  ModelTrendData,
  ModelComparisonResponse,
  ModelSyncConfig,
  ModelSyncConfigCreate,
  ModelSyncConfigUpdate,
  ModelListParams,
  ModelReportListParams,
  ModelTrendParams,
  StartupCommands,
} from '../types/models'

// ============ 模型配置 API ============

/**
 * 获取模型列表
 */
export const getModels = async (params?: ModelListParams): Promise<ModelConfig[]> => {
  const response = await api.get<ModelConfig[]>('/models', { params })
  return response.data
}

/**
 * 获取模型详情
 */
export const getModel = async (modelId: number): Promise<ModelConfig> => {
  const response = await api.get<ModelConfig>(`/models/${modelId}`)
  return response.data
}

/**
 * 创建模型配置
 */
export const createModel = async (data: Partial<ModelConfig>): Promise<ModelConfig> => {
  const response = await api.post<ModelConfig>('/models', data)
  return response.data
}

/**
 * 更新模型配置
 */
export const updateModel = async (
  modelId: number,
  data: Partial<ModelConfig>
): Promise<ModelConfig> => {
  const response = await api.put<ModelConfig>(`/models/${modelId}`, data)
  return response.data
}

/**
 * 删除模型配置
 */
export const deleteModel = async (modelId: number): Promise<{ message: string }> => {
  const response = await api.delete<{ message: string }>(`/models/${modelId}`)
  return response.data
}

// ============ 模型报告 API ============

/**
 * 获取模型报告列表
 */
export const getModelReports = async (
  modelId: number,
  params?: ModelReportListParams
): Promise<ModelReport[]> => {
  const response = await api.get<ModelReport[]>(`/models/${modelId}/reports`, { params })
  return response.data
}

/**
 * 获取最新模型报告
 */
export const getLatestReport = async (modelId: number): Promise<ModelReport> => {
  const response = await api.get<ModelReport>(`/models/${modelId}/reports/latest`)
  return response.data
}

/**
 * 获取指定报告详情
 */
export const getReport = async (modelId: number, reportId: number): Promise<ModelReport> => {
  const response = await api.get<ModelReport>(`/models/${modelId}/reports/${reportId}`)
  return response.data
}

/**
 * 更新报告（管理员可修改 Pass/Fail 等）
 */
export const updateReport = async (
  modelId: number,
  reportId: number,
  data: {
    pass_fail?: string
    auto_pass_fail?: string
    manual_override?: boolean
    metrics_json?: Record<string, any>
    vllm_version?: string
    vllm_ascend_version?: string
    hardware?: string
    report_json?: Record<string, any>
    dtype?: string
    features?: string[]
    serve_cmd?: Record<string, any>
    environment?: Record<string, any>
    tasks?: Record<string, any>[]
  }
): Promise<ModelReport> => {
  const response = await api.put<ModelReport>(`/models/${modelId}/reports/${reportId}`, data)
  return response.data
}

/**
 * 删除报告
 */
export const deleteReport = async (modelId: number, reportId: number): Promise<{ message: string }> => {
  const response = await api.delete<{ message: string }>(`/models/${modelId}/reports/${reportId}`)
  return response.data
}

/**
 * 上传模型报告文件
 */
export const uploadReport = async (
  modelId: number,
  file: File,
  vllmVersion?: string,
  hardware?: string
): Promise<ModelReport> => {
  const formData = new FormData()
  formData.append('file', file)
  if (vllmVersion) formData.append('vllm_version', vllmVersion)
  if (hardware) formData.append('hardware', hardware)

  const response = await api.post<ModelReport>(
    `/models/${modelId}/reports/upload`,
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    }
  )
  return response.data
}

/**
 * 手动触发报告同步
 */
export const syncReports = async (modelId: number): Promise<{ message: string }> => {
  const response = await api.post<{ message: string }>(`/models/${modelId}/reports/sync`)
  return response.data
}

// ============ 趋势分析 API ============

/**
 * 获取模型趋势数据
 */
export const getModelTrends = async (
  modelId: number,
  params?: ModelTrendParams
): Promise<ModelTrendData[]> => {
  const response = await api.get<ModelTrendData[]>(`/models/${modelId}/trends`, { params })
  return response.data
}

/**
 * 对比两个报告
 */
export const compareReports = async (
  modelId: number,
  reportIds: number[]
): Promise<ModelComparisonResponse> => {
  const response = await api.get<ModelComparisonResponse>(
    `/models/${modelId}/reports/compare`,
    {
      params: { report_ids: reportIds.join(',') },
    }
  )
  return response.data
}

// ============ 启动命令 API ============

/**
 * 获取启动命令（多版本）
 */
export const getStartupCommands = async (modelId: number): Promise<StartupCommands> => {
  const response = await api.get<StartupCommands>(`/models/${modelId}/startup-commands`)
  return response.data
}

/**
 * 更新启动命令
 */
export const updateStartupCommands = async (
  modelId: number,
  commands: Record<string, string>
): Promise<StartupCommands> => {
  const response = await api.put<StartupCommands>(
    `/models/${modelId}/startup-commands`,
    commands
  )
  return response.data
}

/**
 * 从 YAML 配置生成启动命令
 */
export const generateStartupCommand = async (
  modelId: number,
  vllmVersion?: string
): Promise<StartupCommands> => {
  const response = await api.post<StartupCommands>(
    `/models/${modelId}/startup-commands/generate`,
    null,
    { params: { vllm_version: vllmVersion } }
  )
  return response.data
}

// ============ 同步配置 API ============

/**
 * 获取同步配置列表
 */
export const getSyncConfigs = async (enabled?: boolean): Promise<ModelSyncConfig[]> => {
  const response = await api.get<ModelSyncConfig[]>('/model-sync-configs', {
    params: { enabled },
  })
  return response.data
}

/**
 * 获取同步配置详情
 */
export const getSyncConfig = async (configId: number): Promise<ModelSyncConfig> => {
  const response = await api.get<ModelSyncConfig>(`/model-sync-configs/${configId}`)
  return response.data
}

/**
 * 创建同步配置
 */
export const createSyncConfig = async (
  data: ModelSyncConfigCreate
): Promise<ModelSyncConfig> => {
  const response = await api.post<ModelSyncConfig>('/model-sync-configs', data)
  return response.data
}

/**
 * 更新同步配置
 */
export const updateSyncConfig = async (
  configId: number,
  data: ModelSyncConfigUpdate
): Promise<ModelSyncConfig> => {
  const response = await api.put<ModelSyncConfig>(
    `/model-sync-configs/${configId}`,
    data
  )
  return response.data
}

/**
 * 删除同步配置
 */
export const deleteSyncConfig = async (configId: number): Promise<{ message: string }> => {
  const response = await api.delete<{ message: string }>(
    `/model-sync-configs/${configId}`
  )
  return response.data
}

/**
 * 手动触发同步
 */
export const triggerSync = async (configId: number): Promise<{ message: string }> => {
  const response = await api.post<{ message: string }>(
    `/model-sync-configs/${configId}/sync`
  )
  return response.data
}

/**
 * 同步所有配置
 */
export const syncAllConfigs = async (): Promise<{ message: string }> => {
  const response = await api.post<{ message: string }>('/model-sync-configs/sync-all')
  return response.data
}

// ============ 支持矩阵 API ============

import type {
  SupportMatrixResponse,
  FeatureCompatResponse,
  GlobalFeaturesResponse,
  SyncStatus,
  SyncResult,
} from '../types/models'

export const getSupportMatrix = async (params?: {
  model_type?: string
  role?: string
  series?: string
  support_status?: string
  tier?: string
}): Promise<SupportMatrixResponse> => {
  const response = await api.get<SupportMatrixResponse>('/models/support-matrix', { params })
  return response.data
}

export const getFeatureCompatibility = async (): Promise<FeatureCompatResponse> => {
  const response = await api.get<FeatureCompatResponse>('/models/feature-compatibility')
  return response.data
}

export const getGlobalFeatures = async (): Promise<GlobalFeaturesResponse> => {
  const response = await api.get<GlobalFeaturesResponse>('/models/global-features')
  return response.data
}

export const getSyncStatus = async (): Promise<SyncStatus> => {
  const response = await api.get<SyncStatus>('/models/sync-status')
  return response.data
}

export const triggerUpstreamSync = async (dryRun: boolean = false): Promise<SyncResult> => {
  const response = await api.post<SyncResult>('/models/sync-upstream', null, {
    params: { dry_run: dryRun },
  })
  return response.data
}
