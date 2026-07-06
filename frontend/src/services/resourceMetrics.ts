import api from './api'

export interface NpuMetricPoint {
  collected_at: string
  npu_utilization: number
  npu_total: number
  npu_used: number
  npu_available: number
  executing_pods_count: number
  pr_count: number
  top_pods: TopPodInfo[]
}

export interface TopPodInfo {
  name: string
  namespace: string
  npu: number
  pr_number: number | null
  pr_url: string | null
  phase: string | null
}

export interface ClusterNpuMetrics {
  cluster_id: number
  cluster_name: string
  metrics: NpuMetricPoint[]
}

export interface NpuMetricsResponse {
  clusters: ClusterNpuMetrics[]
}

export interface NodeMetricPoint {
  collected_at: string
  npu_utilization: number
  npu_total: number
  npu_used: number
  npu_available: number
  cpu_utilization: number
  memory_utilization: number
  executing_pods_count: number
}

export interface NodeSeries {
  node_name: string
  metrics: NodeMetricPoint[]
}

export interface ClusterNodeMetrics {
  cluster_id: number
  cluster_name: string
  nodes: NodeSeries[]
}

export interface NodeMetricsResponse {
  clusters: ClusterNodeMetrics[]
}

export interface ResourceMetricsConfig {
  interval_minutes: number
  retention_days: number
}

export interface ResourceMetricsConfigUpdate {
  interval_minutes?: number
  retention_days?: number
}

export const getNpuMetrics = async (params: {
  cluster_ids?: number[]
  time_range?: string
  start_time?: string
  end_time?: string
} = {}) => {
  const searchParams = new URLSearchParams()
  if (params.time_range) {
    searchParams.append('time_range', params.time_range)
  }
  if (params.start_time) {
    searchParams.append('start_time', params.start_time)
  }
  if (params.end_time) {
    searchParams.append('end_time', params.end_time)
  }
  params.cluster_ids?.forEach(id => searchParams.append('cluster_ids', String(id)))
  const response = await api.get<NpuMetricsResponse>('/resource-dashboard/metrics/npu', {
    params: searchParams,
  })
  return response.data
}

export const getNodeMetrics = async (params: {
  cluster_ids?: number[]
  node_names?: string[]
  time_range?: string
  start_time?: string
  end_time?: string
} = {}) => {
  const searchParams = new URLSearchParams()
  if (params.time_range) {
    searchParams.append('time_range', params.time_range)
  }
  if (params.start_time) {
    searchParams.append('start_time', params.start_time)
  }
  if (params.end_time) {
    searchParams.append('end_time', params.end_time)
  }
  params.cluster_ids?.forEach(id => searchParams.append('cluster_ids', String(id)))
  params.node_names?.forEach(name => searchParams.append('node_names', name))
  const response = await api.get<NodeMetricsResponse>('/resource-dashboard/metrics/nodes', {
    params: searchParams,
  })
  return response.data
}

export const getResourceMetricsConfig = async () => {
  const response = await api.get<ResourceMetricsConfig>('/resource-dashboard/metrics/config')
  return response.data
}

export const updateResourceMetricsConfig = async (data: ResourceMetricsConfigUpdate) => {
  const response = await api.put<ResourceMetricsConfig>('/resource-dashboard/metrics/config', data)
  return response.data
}