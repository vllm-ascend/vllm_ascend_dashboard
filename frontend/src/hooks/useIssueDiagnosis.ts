import { useState, useCallback, useEffect } from 'react'
import { message } from 'antd'
import {
  IssueDiagnosisRequest,
  CIJobOption,
  getFailedCIJobs,
  streamDiagnosis,
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

    try {
      await streamDiagnosis(
        request,
        (chunk) => setStreamContent(prev => prev + chunk),
        (m) => setMeta(m),
        (s) => { setSummary(s); setIsStreaming(false) },
        (errMsg) => { setError(errMsg); setIsStreaming(false) },
      )
    } catch (e: any) {
      setError(e.message || '诊断请求失败')
    } finally {
      setIsStreaming(false)
    }
  }, [dataSourceType, prNumber, selectedJobId, userPrompt, logContent])

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
    setUserPrompt('')
    setLogContent('')
  }, [])

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
    clearError: () => setError(null),
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
