import { useState, useCallback, useEffect } from 'react'
import { message } from 'antd'
import {
  IssueDiagnosisRequest,
  CIJobOption,
  getFailedCIJobs,
  streamDiagnosis,
  saveDiagnosisRecord,
  toggleDiagnosisLike,
} from '../services/issueDiagnosis'
import { diagnosePR } from '../services/prPipeline'
import type { DiagnosisSummary } from '../components/StreamMarkdownRenderer'

export function useIssueDiagnosis() {
  const [dataSourceType, setDataSourceType] = useState<string>('pr_pipeline')
  const [prNumber, setPrNumber] = useState<number | null>(null)
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null)
  const [userPrompt, setUserPrompt] = useState('')
  const [logContent, setLogContent] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamContent, setStreamContent] = useState('')
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

  const handleDataSourceTypeChange = useCallback((type: string) => {
    setDataSourceType(type)
    setSelectedJobId(null)
    setPrNumber(null)
  }, [])

  const handleStartDiagnosis = useCallback(async () => {
    if (dataSourceType === 'pr_pipeline') {
      if (!prNumber) {
        message.warning('请输入 PR 编号')
        return
      }
    } else if (dataSourceType === 'ci_job') {
      if (!selectedJobId && !userPrompt && !logContent) {
        message.warning('请选择 CI Job 或输入提示词/日志内容')
        return
      }
    } else {
      if (!userPrompt && !logContent) {
        message.warning('请输入提示词或日志内容')
        return
      }
    }

    setIsStreaming(true)
    setStreamContent('')
    setMeta(null)
    setSummary(null)
    setError(null)
    setHistoryId(null)
    setIsLiked(false)

    if (dataSourceType === 'pr_pipeline' && prNumber) {
      try {
        const result = await diagnosePR(prNumber)
        setStreamContent(result.report)
        setMeta({ provider: result.provider, model: result.model })
        setSummary({
          total_content_length: result.report.length,
          duration_seconds: result.duration_seconds,
          chunk_count: 1,
        })
        if (result.history_id) setHistoryId(result.history_id)
      } catch (e: any) {
        const errBody = e?.response?.data?.detail
        setError(errBody || e.message || 'PR 诊断请求失败')
      } finally {
        setIsStreaming(false)
      }
      return
    }

    const hasDataSource = dataSourceType === 'ci_job' && selectedJobId
    const effectiveDataSourceType = hasDataSource ? 'ci_job' : 'manual'

    const request: IssueDiagnosisRequest = {
      data_source_type: effectiveDataSourceType as 'ci_job' | 'manual',
    }

    if (dataSourceType === 'ci_job' && selectedJobId) {
      request.job_id = selectedJobId
    }

    let prompt = userPrompt
    if (logContent) {
      prompt = prompt
        ? `${prompt}\n\n### 用户提供的日志内容\n${logContent}`
        : `请分析以下日志内容，定位问题根因并给出改进建议：\n\n${logContent}`
    }
    if (prompt) request.user_prompt = prompt

    const targetId = effectiveDataSourceType === 'ci_job' && selectedJobId
      ? String(selectedJobId)
      : `manual_${Date.now()}`
    let targetLabel: string | undefined
    if (effectiveDataSourceType === 'ci_job' && selectedJobId) {
      const job = ciJobOptions.find(j => j.job_id === selectedJobId)
      targetLabel = job ? `${job.workflow_name} - ${job.job_name}` : undefined
    }

    let accumulated = ''
    let localMeta: { provider: string; model: string } | null = null

    try {
      await streamDiagnosis(
        request,
        (chunk) => { accumulated += chunk; setStreamContent(prev => prev + chunk) },
        (m) => { localMeta = m; setMeta(m) },
        (s) => {
          setSummary(s)
          setIsStreaming(false)
          saveDiagnosisRecord({
            diagnosis_type: effectiveDataSourceType,
            target_id: targetId,
            target_label: targetLabel,
            report_content: accumulated,
            model_used: localMeta?.model,
            duration_seconds: s.duration_seconds,
            status: 'success',
          }).then((res) => {
            if (res.id) setHistoryId(res.id)
          }).catch((err) => console.warn('保存诊断记录失败:', err))
        },
        (errMsg) => { setError(errMsg); setIsStreaming(false) },
      )
    } catch (e: any) {
      setError(e.message || '诊断请求失败')
    } finally {
      setIsStreaming(false)
    }
  }, [dataSourceType, prNumber, selectedJobId, userPrompt, logContent, ciJobOptions])

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(streamContent)
    message.success('已复制到剪贴板')
  }, [streamContent])

  const handleExport = useCallback(() => {
    if (!streamContent) { message.warning('暂无可导出的内容'); return }
    const blob = new Blob([streamContent], { type: 'text/markdown;charset=utf-8' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = `issue_diagnosis_${new Date().toISOString().slice(0, 10)}.md`
    link.click()
    URL.revokeObjectURL(link.href)
    message.success('已导出')
  }, [streamContent])

  const handleReset = useCallback(() => {
    setStreamContent('')
    setMeta(null)
    setSummary(null)
    setError(null)
    setHistoryId(null)
    setIsLiked(false)
    setUserPrompt('')
    setLogContent('')
  }, [])

  const handleLike = useCallback(async () => {
    if (!historyId) return
    try {
      const res = await toggleDiagnosisLike(historyId)
      setIsLiked(res.is_liked)
      message.success(res.is_liked ? '已点赞' : '已取消点赞')
    } catch {
      message.error('点赞失败')
    }
  }, [historyId])

  const handleLogFileUpload = useCallback((file: File) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      const text = e.target?.result as string
      setLogContent(text)
      message.success(`已加载日志文件 (${text.length} 字符)`)
    }
    reader.readAsText(file)
    return false
  }, [])

  return {
    dataSourceType, setDataSourceType,
    prNumber, setPrNumber,
    selectedJobId, setSelectedJobId,
    userPrompt, setUserPrompt,
    logContent, setLogContent,
    isStreaming,
    streamContent,
    meta,
    summary,
    error,
    historyId,
    isLiked,
    clearError: () => setError(null),
    handleLike,
    ciJobOptions,
    loadingJobs,
    handleDataSourceTypeChange,
    handleStartDiagnosis,
    handleCopy,
    handleExport,
    handleReset,
    handleLogFileUpload,
  }
}
