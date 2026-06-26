import api from './api'
import type { SystemConfig, SystemStatus, SyncConfigUpdate, AppConfigUpdate, GitHubConfigUpdate } from '../types/systemConfig'

export interface GitRepoStatus {
  owner: string
  repo: string
  latest_commit: {
    sha: string
    subject: string
    author_name: string
    author_email: string
    date: string
  } | null
  cache_dir: string
  is_cloned: boolean
}

export interface GitCacheStatus {
  repositories: {
    ascend: GitRepoStatus
    vllm: GitRepoStatus
  }
  // 向后兼容
  latest_commit: {
    sha: string
    subject: string
    author_name: string
    author_email: string
    date: string
  } | null
  cache_dir: string
  is_cloned: boolean
}

/**
 * 获取系统配置
 */
export const getSystemConfig = async (): Promise<SystemConfig> => {
  const response = await api.get<SystemConfig>('/system/config')
  return response.data
}

/**
 * 更新应用配置
 */
export const updateAppConfig = async (data: AppConfigUpdate): Promise<{ success: boolean; message: string; updates: string[] }> => {
  const response = await api.put('/system/config/app', null, {
    params: data,
  })
  return response.data
}

/**
 * 更新 GitHub 配置
 */
export const updateGitHubConfig = async (data: GitHubConfigUpdate): Promise<{ success: boolean; message: string; updates: string[] }> => {
  const response = await api.put('/system/config/github', null, {
    params: data,
  })
  return response.data
}

/**
 * 更新同步配置
 */
export const updateSyncConfig = async (data: SyncConfigUpdate): Promise<{ success: boolean; message: string; updates: string[] }> => {
  const response = await api.put('/system/config/sync', null, {
    params: data,
  })
  return response.data
}

/**
 * 获取系统状态
 */
export const getSystemStatus = async (): Promise<SystemStatus> => {
  const response = await api.get<SystemStatus>('/system/config/status')
  return response.data
}

/**
 * 获取 Git 缓存状态
 */
export const getGitCacheStatus = async (): Promise<GitCacheStatus> => {
  const response = await api.get<GitCacheStatus>('/system/config/git-cache/status')
  return response.data
}

/**
 * 同步 Git 缓存
 */
export const syncGitCache = async (repoType: string = 'all'): Promise<{ success: boolean; results: Array<{ repo: string; action: string; success: boolean; message: string }> }> => {
  const response = await api.post('/system/config/git-cache/sync', null, {
    params: { repo_type: repoType },
  })
  return response.data
}

/**
 * 触发配置重载
 */
export const triggerConfigReload = async (): Promise<{ success: boolean; message: string }> => {
  const response = await api.post('/system/config/sync/trigger')
  return response.data
}

// Claude Code CLI config
export interface ClaudeCLIConfig {
  max_turns: number
  timeout_seconds: number
}

export const getClaudeCLIConfig = async (): Promise<ClaudeCLIConfig> => {
  const response = await api.get('/ci/claude-cli-config')
  return response.data
}

export const updateClaudeCLIConfig = async (config: Partial<ClaudeCLIConfig>): Promise<ClaudeCLIConfig> => {
  const response = await api.put('/ci/claude-cli-config', config)
  return response.data
}
