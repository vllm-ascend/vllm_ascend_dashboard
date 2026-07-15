import { useState, useCallback, useEffect } from 'react'
import { message } from 'antd'
import {
  IssueDiagnosisRequest,
  type DiagnosisMessage,
  CIJobOption,
  getFailedCIJobs,
  streamDiagnosis,
  saveDiagnosisRecord,
  toggleDiagnosisLike,
} from '../services/issueDiagnosis'
import { buildFollowUpRequest } from '../services/issueDiagnosisConversation'
import type { DiagnosisSummary } from '../components/StreamMarkdownRenderer'

function appendAssistantChunk(messages: DiagnosisMessage[], chunk: string): DiagnosisMessage[] {
  const next = [...messages]
  const last = next[next.length - 1]
  if (!last || last.role !== 'assistant') return next
  next[next.length - 1] = { ...last, content: last.content + chunk }
  return next
}

function formatConversation(messages: DiagnosisMessage[]): string {
  return messages
    .map(item => `## ${item.role === 'assistant' ? 'AI 分析' : '追问'}\n\n${item.content}`)
    .join('\n\n')
}

export function useIssueDiagnosis() {
  const [dataSourceType, setDataSourceType] = useState<string>('pr_pipeline')
  const [prNumber, setPrNumber] = useState<number | null>(null)
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null)
  const [userPrompt, setUserPrompt] = useState('')
  const [logContent, setLogContent] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamContent, setStreamContent] = useState('')
  const [conversation, setConversation] = useState<DiagnosisMessage[]>([])
  const [baseRequest, setBaseRequest] = useState<IssueDiagnosisRequest | null>(null)
  const [followUpQuestion, setFollowUpQuestion] = useState('')
  const [meta, setMeta] = useState<{ provider: string; model: string } | null>(null)
  const [summary, setSummary] = useState<DiagnosisSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [historyId, setHistoryId] = useState<number | null>(null)
  const [isLiked, setIsLiked] = useState(false)

  const [ciJobOptions, setCiJobOptions] = useState<CIJobOption[]>([])
  const [loadingJobs, setLoadingJobs] = useState(false)

  const loadCIJobs = useCallback(async () => {
    setLoadingJobs(true)
    try {
      const jobs = await getFailedCIJobs(7)
      setCiJobOptions(jobs)
    } catch {
      message.error('获取CI Job列表失败')
    } finally {
      setLoadingJobs(false)
    }
  }, [])

  useEffect(() => {
    if (dataSourceType === 'ci_job' && ciJobOptions.length === 0) loadCIJobs()
  }, [dataSourceType, ciJobOptions.length, loadCIJobs])

  const clearDiagnosis = useCallback(() => {
    setStreamContent('')
    setConversation([])
    setBaseRequest(null)
    setFollowUpQuestion('')
    setMeta(null)
    setSummary(null)
    setError(null)
    setHistoryId(null)
    setIsLiked(false)
  }, [])

  const handleDataSourceTypeChange = useCallback((type: string) => {
    setDataSourceType(type)
    setSelectedJobId(null)
    setPrNumber(null)
    clearDiagnosis()
  }, [clearDiagnosis])

  const handleStartDiagnosis = useCallback(async () => {
    if (dataSourceType === 'pr_pipeline' && !prNumber) {
      message.warning('请输入 PR 编号')
      return
    }
    if (dataSourceType === 'ci_job' && !selectedJobId && !userPrompt && !logContent) {
      message.warning('请选择 CI Job 或输入提示词/日志内容')
      return
    }
    if (dataSourceType === 'manual' && !userPrompt && !logContent) {
      message.warning('请输入提示词或日志内容')
      return
    }

    const effectiveType = dataSourceType === 'ci_job' && !selectedJobId
      ? 'manual'
      : dataSourceType as IssueDiagnosisRequest['data_source_type']
    const request: IssueDiagnosisRequest = { data_source_type: effectiveType }
    if (effectiveType === 'pr_pipeline' && prNumber) request.pr_number = prNumber
    if (effectiveType === 'ci_job' && selectedJobId) request.job_id = selectedJobId

    let prompt = userPrompt
    if (logContent) {
      prompt = prompt
        ? `${prompt}\n\n### 用户提供的日志内容\n${logContent}`
        : `请分析以下日志内容，定位问题根因并给出改进建议：\n\n${logContent}`
    }
    if (prompt) request.user_prompt = prompt

    const targetId = effectiveType === 'pr_pipeline'
      ? String(prNumber)
      : effectiveType === 'ci_job' && selectedJobId
        ? String(selectedJobId)
        : `manual_${Date.now()}`
    let targetLabel: string | undefined
    if (effectiveType === 'pr_pipeline') targetLabel = `PR #${prNumber}`
    if (effectiveType === 'ci_job' && selectedJobId) {
      const job = ciJobOptions.find(item => item.job_id === selectedJobId)
      targetLabel = job ? `${job.workflow_name} - ${job.job_name}` : undefined
    }

    setIsStreaming(true)
    setStreamContent('')
    setConversation([{ role: 'assistant', content: '' }])
    setBaseRequest(request)
    setMeta(null)
    setSummary(null)
    setError(null)
    setHistoryId(null)
    setIsLiked(false)

    let accumulated = ''
    let localMeta: { provider: string; model: string } | null = null

    try {
      await streamDiagnosis(
        request,
        chunk => {
          accumulated += chunk
          setStreamContent(previous => previous + chunk)
          setConversation(previous => appendAssistantChunk(previous, chunk))
        },
        value => { localMeta = value; setMeta(value) },
        value => {
          setSummary(value)
          if (accumulated.trim()) {
            saveDiagnosisRecord({
              diagnosis_type: effectiveType,
              target_id: targetId,
              target_label: targetLabel,
              report_content: accumulated,
              model_used: localMeta?.model,
              duration_seconds: value.duration_seconds,
              status: 'success',
            }).then(result => {
              if (result.id) setHistoryId(result.id)
            }).catch(saveError => console.warn('保存诊断记录失败:', saveError))
          }
        },
        errorMessage => setError(errorMessage),
      )
    } catch (requestError: any) {
      setError(requestError.message || '诊断请求失败')
    } finally {
      setIsStreaming(false)
    }
  }, [dataSourceType, prNumber, selectedJobId, userPrompt, logContent, ciJobOptions])

  const handleFollowUp = useCallback(async () => {
    const question = followUpQuestion.trim()
    if (!question || !baseRequest || !conversation.length) return

    const request = buildFollowUpRequest(baseRequest, conversation, question)
    setConversation(previous => [
      ...previous,
      { role: 'user', content: question },
      { role: 'assistant', content: '' },
    ])
    setFollowUpQuestion('')
    setError(null)
    setSummary(null)
    setIsStreaming(true)

    try {
      await streamDiagnosis(
        request,
        chunk => setConversation(previous => appendAssistantChunk(previous, chunk)),
        setMeta,
        setSummary,
        errorMessage => setError(errorMessage),
      )
    } catch (requestError: any) {
      setError(requestError.message || '追问请求失败')
    } finally {
      setIsStreaming(false)
    }
  }, [followUpQuestion, baseRequest, conversation])

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(formatConversation(conversation))
    message.success('已复制到剪贴板')
  }, [conversation])

  const handleExport = useCallback(() => {
    if (!conversation.length) { message.warning('暂无可导出的内容'); return }
    const blob = new Blob([formatConversation(conversation)], { type: 'text/markdown;charset=utf-8' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = `issue_diagnosis_${new Date().toISOString().slice(0, 10)}.md`
    link.click()
    URL.revokeObjectURL(link.href)
    message.success('已导出')
  }, [conversation])

  const handleReset = useCallback(() => {
    clearDiagnosis()
    setUserPrompt('')
    setLogContent('')
  }, [clearDiagnosis])

  const handleLike = useCallback(async () => {
    if (!historyId) return
    try {
      const result = await toggleDiagnosisLike(historyId)
      setIsLiked(result.is_liked)
      message.success(result.is_liked ? '已点赞' : '已取消点赞')
    } catch {
      message.error('点赞失败')
    }
  }, [historyId])

  const handleLogFileUpload = useCallback((file: File) => {
    const reader = new FileReader()
    reader.onload = event => {
      const text = event.target?.result as string
      setLogContent(text)
      message.success(`已加载日志文件 (${text.length} 字符)`)
    }
    reader.readAsText(file)
    return false
  }, [])

  return {
    dataSourceType,
    prNumber,
    selectedJobId,
    userPrompt,
    logContent,
    isStreaming,
    streamContent,
    conversation,
    followUpQuestion,
    meta,
    summary,
    error,
    historyId,
    isLiked,
    ciJobOptions,
    loadingJobs,
    setPrNumber,
    setSelectedJobId,
    setUserPrompt,
    setLogContent,
    setFollowUpQuestion,
    clearError: () => setError(null),
    handleLike,
    handleDataSourceTypeChange,
    handleStartDiagnosis,
    handleFollowUp,
    handleCopy,
    handleExport,
    handleReset,
    handleLogFileUpload,
  }
}
