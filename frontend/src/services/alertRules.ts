import api from './api'

export interface AlertCondition {
  id?: number
  group_id?: number
  metric_field: string
  operator: string
  threshold: number
  is_exclude: boolean
  display_order?: number
}

export interface AlertConditionGroup {
  id?: number
  rule_id?: number
  logic: 'AND' | 'OR'
  display_order?: number
  conditions: AlertCondition[]
}

export interface AlertRule {
  id: number
  user_id: number
  name: string
  cluster_id: number | null
  node_name: string | null
  enabled: boolean
  notify_email: boolean
  notification_email: string | null
  last_triggered_at: string | null
  created_at: string
  updated_at: string
  groups: AlertConditionGroup[]
}

export interface AlertRuleCreate {
  name: string
  cluster_id?: number | null
  node_name?: string | null
  enabled?: boolean
  notify_email?: boolean
  notification_email?: string | null
  groups: { logic: string; conditions: AlertCondition[] }[]
}

export interface AlertRuleUpdate {
  name?: string
  cluster_id?: number | null
  node_name?: string | null
  enabled?: boolean
  notify_email?: boolean
  notification_email?: string | null
  groups?: { logic: string; conditions: AlertCondition[] }[]
}

export interface AlertHistory {
  id: number
  rule_id: number
  rule_name: string
  actual_value: number
  cluster_id: number | null
  cluster_name: string | null
  node_name: string | null
  condition_details: any
  triggered_at: string
  notification_sent: boolean
  notification_error: string | null
}

export const METRIC_FIELD_OPTIONS = [
  { label: '--- 集群级 ---', value: '', disabled: true },
  { label: 'NPU 利用率 (%)', value: 'npu_utilization' },
  { label: 'NPU 总量 (卡)', value: 'npu_total' },
  { label: 'NPU 已用 (卡)', value: 'npu_used' },
  { label: 'NPU 可用 (卡)', value: 'npu_available' },
  { label: '执行中 Pod 数', value: 'executing_pods_count' },
  { label: '活跃 PR 数', value: 'pr_count' },
  { label: '--- 节点级 ---', value: '', disabled: true },
  { label: 'CPU 利用率 (%)', value: 'cpu_utilization' },
  { label: '内存利用率 (%)', value: 'memory_utilization' },
  { label: 'CPU 已用 (核)', value: 'cpu_cores_used' },
  { label: 'CPU 总量 (核)', value: 'cpu_cores_total' },
  { label: '内存已用 (GiB)', value: 'memory_bytes_used' },
  { label: '内存总量 (GiB)', value: 'memory_bytes_total' },
]

export const OPERATOR_OPTIONS = [
  { label: '> (大于)', value: '>' },
  { label: '< (小于)', value: '<' },
  { label: '>= (大于等于)', value: '>=' },
  { label: '<= (小于等于)', value: '<=' },
  { label: '== (等于)', value: '==' },
]

export const getAlertRules = async (): Promise<AlertRule[]> => {
  const response = await api.get<AlertRule[]>('/alert-rules')
  return response.data
}

export const createAlertRule = async (data: AlertRuleCreate): Promise<AlertRule> => {
  const response = await api.post<AlertRule>('/alert-rules', data)
  return response.data
}

export const updateAlertRule = async (ruleId: number, data: AlertRuleUpdate): Promise<AlertRule> => {
  const response = await api.put<AlertRule>(`/alert-rules/${ruleId}`, data)
  return response.data
}

export const deleteAlertRule = async (ruleId: number): Promise<{ message: string }> => {
  const response = await api.delete<{ message: string }>(`/alert-rules/${ruleId}`)
  return response.data
}

export const getAlertRuleHistory = async (ruleId: number): Promise<AlertHistory[]> => {
  const response = await api.get<AlertHistory[]>(`/alert-rules/${ruleId}/history`)
  return response.data
}
