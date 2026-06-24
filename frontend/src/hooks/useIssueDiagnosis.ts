import { useState, useCallback, useEffect } from 'react'
import { message } from 'antd'
import {
  IssueDiagnosisRequest,
  CIJobOption,
  CommitOption,
  getFailedCIJobs,
  getRecentCommits,
  streamDiagnosis,
} from '../services/issueDiagnosis'
import type { DiagnosisSummary } from '../components/StreamMarkdownRenderer'

export function useIssueDiagnosis() {
  const [dataSourceType, setDataSourceType] = useState<string>('ci_job')
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null)
  const [selectedCommitSha, setSelectedCommitSha] = useState<string | null>(null)
  const [userPrompt, setUserPrompt] = useState('')
  const [logContent, setLogContent] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamContent, setStreamContent] = useState('')
  const [meta, setMeta] = useState<{ provider: string; model: string } | null>(null)
  const [summary, setSummary] = useState<DiagnosisSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [ciJobOptions, setCiJobOptions] = useState<CIJobOption[]>([])
  const [commitOptions, setCommitOptions] = useState<CommitOption[]>([])
  const [loadingJobs, setLoadingJobs] = useState(false)
  const [loadingCommits, setLoadingCommits] = useState(false)

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

  const loadCommits = useCallback(async () => {
    setLoadingCommits(true)
    try {
      const commits = await getRecentCommits(7)
      setCommitOptions(commits)
    } catch {
      message.error('获取Commit列表失败')
    } finally {
      setLoadingCommits(false)
    }
  }, [])

  useEffect(() => {
    if (dataSourceType === 'ci_job' && ciJobOptions.length === 0) loadCIJobs()
    if (dataSourceType === 'commit' && commitOptions.length === 0) loadCommits()
  }, [dataSourceType, ciJobOptions.length, commitOptions.length, loadCIJobs, loadCommits])

  const handleDataSourceTypeChange = useCallback((type: string) => {
    setDataSourceType(type)
    setSelectedJobId(null)
    setSelectedCommitSha(null)
  }, [])

  const handleStartDiagnosis = useCallback(async () => {
    const hasPromptOrLog = !!userPrompt || !!logContent
    const hasDataSource = (dataSourceType === 'ci_job' && selectedJobId) ||
      (dataSourceType === 'commit' && selectedCommitSha)

    if (!hasPromptOrLog && !hasDataSource) {
      message.warning('请选择数据源或输入提示词/日志内容')
      return
    }

    setIsStreaming(true)
    setStreamContent('')
    setMeta(null)
    setSummary(null)
    setError(null)

    const effectiveDataSourceType = hasDataSource ? dataSourceType : 'manual'

    const request: IssueDiagnosisRequest = {
      data_source_type: effectiveDataSourceType as 'ci_job' | 'commit' | 'manual',
    }

    if (dataSourceType === 'ci_job' && selectedJobId) {
      request.job_id = selectedJobId
    } else if (dataSourceType === 'commit' && selectedCommitSha) {
      const selectedCommit = commitOptions.find(c => c.sha === selectedCommitSha)
      if (selectedCommit?.run_id) request.run_id = selectedCommit.run_id
      request.commit_sha = selectedCommitSha
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
  }, [dataSourceType, selectedJobId, selectedCommitSha, userPrompt, logContent, commitOptions])

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
    selectedJobId, setSelectedJobId,
    selectedCommitSha, setSelectedCommitSha,
    userPrompt, setUserPrompt,
    logContent, setLogContent,
    isStreaming,
    streamContent,
    meta,
    summary,
    error,
    clearError: () => setError(null),
    ciJobOptions,
    commitOptions,
    loadingJobs,
    loadingCommits,
    handleDataSourceTypeChange,
    handleStartDiagnosis,
    handleCopy,
    handleExport,
    handleReset,
    handleLogFileUpload,
  }
}
