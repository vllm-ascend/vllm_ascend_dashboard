import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as ciApi from '../services/ci'

/**
 * 获取 workflow 列表
 */
export const useWorkflows = () => {
  return useQuery({
    queryKey: ['ci-workflows'],
    queryFn: ciApi.getWorkflows,
  })
}

/**
 * 获取 CI 运行列表
 */
export const useRuns = (params?: {
  workflow_name?: string
  status?: string
  hardware?: string
  limit?: number
}) => {
  return useQuery({
    queryKey: ['ci-runs', params],
    queryFn: () => ciApi.getRuns(params),
  })
}

/**
 * 获取 CI 统计数据
 */
export const useCIStats = (params?: {
  workflow_name?: string
  hardware?: string
}) => {
  return useQuery({
    queryKey: ['ci-stats', params],
    queryFn: () => ciApi.getStats(params),
  })
}

/**
 * 获取 CI 趋势数据
 */
export const useCITrends = (params: {
  days?: number
  workflow_name?: string
  hardware?: string
}) => {
  return useQuery({
    queryKey: ['ci-trends', params],
    queryFn: () => ciApi.getTrends(params),
  })
}

/**
 * 获取指定 run 的 jobs
 */
export const useJobsByRun = (runId: number | null) => {
  return useQuery({
    queryKey: ['ci-jobs', runId],
    queryFn: () => runId ? ciApi.getJobsByRun(runId) : Promise.resolve([]),
    enabled: !!runId,
  })
}

/**
 * 获取 job 详情
 */
export const useJobDetail = (jobId: number | null) => {
  return useQuery({
    queryKey: ['ci-job-detail', jobId],
    queryFn: () => jobId ? ciApi.getJobDetail(jobId) : Promise.resolve(null),
    enabled: !!jobId,
  })
}

/**
 * 手动触发数据同步
 */
export const useSyncCI = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ciApi.triggerSync,
    onSuccess: () => {
      // 同步成功后刷新相关数据
      queryClient.invalidateQueries({ queryKey: ['ci-runs'] })
      queryClient.invalidateQueries({ queryKey: ['ci-stats'] })
      queryClient.invalidateQueries({ queryKey: ['ci-trends'] })
      queryClient.invalidateQueries({ queryKey: ['ci-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['ci-job-detail'] })
    },
  })
}

/**
 * 获取同步任务状态
 */
export const useSyncStatus = () => {
  return useQuery({
    queryKey: ['ci-sync-status'],
    queryFn: ciApi.getSyncStatus,
    // 每 30 秒轮询一次
    refetchInterval: 30000,
  })
}

/**
 * 获取同步进度详情（高频轮询）
 */
export const useSyncProgress = (enabled: boolean = false) => {
  return useQuery({
    queryKey: ['ci-sync-progress'],
    queryFn: ciApi.getSyncProgress,
    // 每 2 秒轮询一次
    refetchInterval: enabled ? 2000 : false,
    enabled: enabled,
  })
}
