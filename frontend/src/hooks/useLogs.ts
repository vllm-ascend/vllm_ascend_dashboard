import { useQuery } from '@tanstack/react-query'
import * as logsApi from '../services/logs'
import type { LogQueryRequest } from '../services/logs'

/**
 * 获取日志源列表（每分钟自动刷新）
 */
export const useLogSources = () => {
  return useQuery({
    queryKey: ['log-sources'],
    queryFn: logsApi.getLogSources,
    refetchInterval: 60_000,
  })
}

/**
 * 统一日志查询
 */
export const useLogQuery = (filters: LogQueryRequest) => {
  return useQuery({
    queryKey: ['log-query', filters],
    queryFn: () => logsApi.queryLogs(filters),
    placeholderData: (prev) => prev,
  })
}

/**
 * 获取单条日志详情（点击展开时按需加载）
 */
export const useLogEntry = (logId: string | null) => {
  return useQuery({
    queryKey: ['log-entry', logId],
    queryFn: () =>
      logId ? logsApi.getLogEntry(logId) : Promise.resolve(null),
    enabled: !!logId,
  })
}
