const API_BASE_URL = (typeof import.meta !== 'undefined' &&
  (import.meta as any).env?.VITE_API_BASE_URL) || 'http://localhost:8000/api/v1'

export interface IssueDiagnosisRequest {
  data_source_type: 'ci_job' | 'commit' | 'manual'
  job_id?: number
  run_id?: number
  commit_sha?: string
  user_prompt?: string
}

export interface CIJobOption {
  job_id: number
  run_id: number
  workflow_name: string
  job_name: string
  conclusion: string
  completed_at: string | null
}

export interface CommitOption {
  sha: string
  message: string
  committed_at: string | null
  run_id: number | null
  run_number: number | null
}

export const getFailedCIJobs = async (daysBack: number = 7): Promise<CIJobOption[]> => {
  const token = localStorage.getItem('access_token')
  const response = await fetch(
    `${API_BASE_URL}/issue-diagnosis/data-sources/ci-jobs?days_back=${daysBack}`,
    {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    }
  )
  if (!response.ok) {
    throw new Error(`Failed to fetch CI jobs: ${response.statusText}`)
  }
  return response.json()
}

export const getRecentCommits = async (daysBack: number = 7): Promise<CommitOption[]> => {
  const token = localStorage.getItem('access_token')
  const response = await fetch(
    `${API_BASE_URL}/issue-diagnosis/data-sources/commits?days_back=${daysBack}`,
    {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    }
  )
  if (!response.ok) {
    throw new Error(`Failed to fetch commits: ${response.statusText}`)
  }
  return response.json()
}

export const streamDiagnosis = async (
  request: IssueDiagnosisRequest,
  onChunk: (content: string) => void,
  onMeta: (meta: { provider: string; model: string }) => void,
  onDone: (summary: { total_content_length: number; duration_seconds: number; chunk_count: number }) => void,
  onError: (message: string) => void,
): Promise<void> => {
  const token = localStorage.getItem('access_token')

  const response = await fetch(
    `${API_BASE_URL}/issue-diagnosis/diagnose`,
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    }
  )

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: response.statusText }))
    onError(errorData.detail || response.statusText)
    return
  }

  const reader = response.body?.getReader()
  if (!reader) {
    onError('No response body')
    return
  }

  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (line.startsWith('event:') || line.startsWith('event: ')) {
        currentEvent = line.slice(line.indexOf(':') + 1).trim()
      } else if (line.startsWith('data:') || line.startsWith('data: ')) {
        const dataStr = line.slice(line.indexOf(':') + 1).trim()
        try {
          const data = JSON.parse(dataStr)
          if (currentEvent === 'chunk') {
            onChunk(data.content)
          } else if (currentEvent === 'meta') {
            onMeta(data)
          } else if (currentEvent === 'done') {
            onDone(data)
          } else if (currentEvent === 'error') {
            onError(data.message)
          }
        } catch (e) {
          console.warn('SSE data parse error:', e)
        }
        currentEvent = ''
      }
    }
  }
}
