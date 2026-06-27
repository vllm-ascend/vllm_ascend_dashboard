import api from './api'

// ============ Types ============

export interface LogQueryRequest {
  sources?: string[]
  levels?: string[]
  time_range?: {
    start?: string
    end?: string
  }
  search?: string
  page: number
  page_size: number
}

export interface LogEntryMetadata {
  // claude_cli
  provider?: string
  model?: string
  duration_seconds?: number
  exit_code?: number
  route?: string
  // failure_analysis
  workflow_name?: string
  job_name?: string
  job_id?: number
  analysis_status?: string
  // app / scheduler
  module?: string
  function_name?: string
  line_number?: number
  task_name?: string
  status?: string
  [key: string]: unknown  // allow extra fields (extra="allow")
}

export interface LogEntry {
  id: string
  source: string
  level: string
  timestamp: string
  summary: string
  content: string
  metadata: LogEntryMetadata
}

export interface LogQueryResponse {
  total: number
  page: number
  page_size: number
  entries: LogEntry[]
}

export interface LogSource {
  key: string
  label: string
  count: number
  last_entry: string | null
}

export interface LogSourcesResponse {
  sources: LogSource[]
}

// ============ API Functions ============

export const getLogSources = async (): Promise<LogSourcesResponse> => {
  const response = await api.get<LogSourcesResponse>('/logs/sources')
  return response.data
}

export const queryLogs = async (
  filters: LogQueryRequest
): Promise<LogQueryResponse> => {
  const response = await api.post<LogQueryResponse>('/logs/query', filters)
  return response.data
}

export const getLogEntry = async (logId: string): Promise<LogEntry> => {
  const encodedId = encodeURIComponent(logId)
  const response = await api.get<LogEntry>(`/logs/${encodedId}`)
  return response.data
}
