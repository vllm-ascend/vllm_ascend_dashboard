import api from './api'

export interface DailyReportConfig {
  smtp_host: string
  smtp_port: number
  smtp_username: string
  smtp_use_tls: boolean
  smtp_password_set: boolean
  report_from_email: string
  report_recipients: string
  report_cc_recipients: string
  report_subject_template: string
  report_enabled: boolean
  report_schedule_hour: number
  report_schedule_minute: number
}

export interface DailyReportConfigUpdate {
  smtp_host?: string
  smtp_port?: number
  smtp_username?: string
  smtp_password?: string
  smtp_use_tls?: boolean
  report_from_email?: string
  report_recipients?: string
  report_cc_recipients?: string
  report_subject_template?: string
}

export interface DailyReportHistoryItem {
  id: number
  report_date: string
  recipients: string
  subject: string
  status: string
  sent_at: string | null
  error_message: string | null
  ci_summary: Record<string, unknown> | null
  model_summary: Record<string, unknown> | null
  github_summary: Record<string, unknown> | null
  performance_summary: Record<string, unknown> | null
  created_at: string
}

export interface DailyReportHistoryResponse {
  total: number
  items: DailyReportHistoryItem[]
}

export interface DailyReportTriggerResponse {
  success: boolean
  message: string
  report_date: string | null
  report_id: number | null
}

export interface DailyReportLatest {
  id: number
  report_date: string
  subject: string
  status: string
  sent_at: string | null
  ci_summary: Record<string, unknown> | null
  model_summary: Record<string, unknown> | null
  github_summary: Record<string, unknown> | null
  performance_summary: Record<string, unknown> | null
}

export const getReportConfig = async (): Promise<DailyReportConfig> => {
  const response = await api.get<DailyReportConfig>('/daily-report/config')
  return response.data
}

export const updateReportConfig = async (data: DailyReportConfigUpdate): Promise<DailyReportConfig> => {
  const response = await api.put<DailyReportConfig>('/daily-report/config', data)
  return response.data
}

export const triggerReport = async (reportDate?: string): Promise<DailyReportTriggerResponse> => {
  const params = reportDate ? { report_date: reportDate } : {}
  const response = await api.post<DailyReportTriggerResponse>('/daily-report/trigger', null, { params })
  return response.data
}

export const getReportHistory = async (limit = 20, offset = 0): Promise<DailyReportHistoryResponse> => {
  const response = await api.get<DailyReportHistoryResponse>('/daily-report/history', { params: { limit, offset } })
  return response.data
}

export const getLatestReport = async (): Promise<DailyReportLatest | { message: string; data: null }> => {
  const response = await api.get('/daily-report/latest')
  return response.data
}