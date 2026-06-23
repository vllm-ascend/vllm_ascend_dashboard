import React, { useState, useCallback, useEffect } from 'react'
import {
  Modal,
  Form,
  Select,
  Input,
  Button,
  Space,
  Alert,
  message,
} from 'antd'
import { RobotOutlined, CopyOutlined, DownloadOutlined } from '@ant-design/icons'
import StreamMarkdownRenderer from './StreamMarkdownRenderer'
import {
  IssueDiagnosisRequest,
  CIJobOption,
  CommitOption,
  getFailedCIJobs,
  getRecentCommits,
  streamDiagnosis,
} from '../services/issueDiagnosis'

interface IssueDiagnosisModalProps {
  open: boolean
  onClose: () => void
  initialJobId?: number | null
}

const IssueDiagnosisModal: React.FC<IssueDiagnosisModalProps> = ({
  open,
  onClose,
  initialJobId,
}) => {
  const [dataSourceType, setDataSourceType] = useState<string>(
    initialJobId ? 'ci_job' : 'ci_job'
  )
  const [selectedJobId, setSelectedJobId] = useState<number | null>(initialJobId || null)
  const [selectedCommitSha, setSelectedCommitSha] = useState<string | null>(null)
  const [userPrompt, setUserPrompt] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamContent, setStreamContent] = useState('')
  const [meta, setMeta] = useState<{ provider: string; model: string } | null>(null)
  const [summary, setSummary] = useState<any>(null)
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
    if (initialJobId && ciJobOptions.length === 0) {
      loadCIJobs()
    }
  }, [initialJobId])

  const handleDataSourceTypeChange = (type: string) => {
    setDataSourceType(type)
    setSelectedJobId(null)
    setSelectedCommitSha(null)
    if (type === 'ci_job') loadCIJobs()
    if (type === 'commit') loadCommits()
  }

  const handleStartDiagnosis = async () => {
    if (dataSourceType === 'ci_job' && !selectedJobId) {
      message.warning('请选择一个CI Job')
      return
    }

    setIsStreaming(true)
    setStreamContent('')
    setMeta(null)
    setSummary(null)
    setError(null)

    const request: IssueDiagnosisRequest = {
      data_source_type: dataSourceType as 'ci_job' | 'commit' | 'manual',
    }

    if (dataSourceType === 'ci_job') {
      request.job_id = selectedJobId!
    } else if (dataSourceType === 'commit') {
      const selectedCommit = commitOptions.find(c => c.sha === selectedCommitSha)
      if (selectedCommit?.run_id) request.run_id = selectedCommit.run_id
      if (selectedCommitSha) request.commit_sha = selectedCommitSha
    }

    if (userPrompt) request.user_prompt = userPrompt

    try {
      await streamDiagnosis(
        request,
        (chunk) => {
          setStreamContent(prev => prev + chunk)
        },
        (m) => {
          setMeta(m)
        },
        (s) => {
          setSummary(s)
          setIsStreaming(false)
        },
        (errMsg) => {
          setError(errMsg)
          setIsStreaming(false)
        },
      )
    } catch (e: any) {
      setError(e.message || '诊断请求失败')
    } finally {
      setIsStreaming(false)
    }
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(streamContent)
    message.success('已复制到剪贴板')
  }

  const handleExport = () => {
    if (!streamContent) {
      message.warning('暂无可导出的内容')
      return
    }
    const blob = new Blob([streamContent], { type: 'text/markdown;charset=utf-8' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = `issue_diagnosis_${new Date().toISOString().slice(0, 10)}.md`
    link.click()
    URL.revokeObjectURL(link.href)
    message.success('已导出')
  }

  const handleResetAndClose = () => {
    if (isStreaming) {
      message.warning('诊断正在进行中')
      return
    }
    setStreamContent('')
    setMeta(null)
    setSummary(null)
    setError(null)
    setUserPrompt('')
    onClose()
  }

  return (
    <Modal
      title={
        <Space>
          <RobotOutlined />
          <span>问题自动定位</span>
          {meta && (
            <span style={{ fontSize: 12, color: '#999' }}>
              ({meta.provider}/{meta.model})
            </span>
          )}
        </Space>
      }
      open={open}
      onCancel={handleResetAndClose}
      width={1000}
      footer={null}
      destroyOnClose
    >
      <div style={{ display: 'flex', gap: 16, height: 520 }}>
        <div style={{ width: 320, flexShrink: 0 }}>
          <Form layout="vertical" size="small">
            <Form.Item label="数据源类型">
              <Select
                value={dataSourceType}
                onChange={handleDataSourceTypeChange}
                options={[
                  { label: 'CI Job (失败诊断)', value: 'ci_job' },
                  { label: 'Commit (代码分析)', value: 'commit' },
                  { label: '手动输入', value: 'manual' },
                ]}
              />
            </Form.Item>

            {dataSourceType === 'ci_job' && (
              <Form.Item label="选择 CI Job">
                <Select
                  value={selectedJobId}
                  onChange={setSelectedJobId}
                  loading={loadingJobs}
                  placeholder="请选择一个失败的CI Job"
                  showSearch
                  optionFilterProp="label"
                  options={ciJobOptions.map(j => ({
                    value: j.job_id,
                    label: `#${j.job_id} ${j.workflow_name} - ${j.job_name} (${j.conclusion})`,
                  }))}
                  onDropdownVisibleChange={(visible) => {
                    if (visible && ciJobOptions.length === 0) loadCIJobs()
                  }}
                />
              </Form.Item>
            )}

            {dataSourceType === 'commit' && (
              <Form.Item label="选择 Commit">
                <Select
                  value={selectedCommitSha}
                  onChange={setSelectedCommitSha}
                  loading={loadingCommits}
                  placeholder="请选择一个commit"
                  showSearch
                  optionFilterProp="label"
                  options={commitOptions.map(c => ({
                    value: c.sha,
                    label: `${c.sha.slice(0, 7)} Run #${c.run_number || '-'}`,
                  }))}
                  onDropdownVisibleChange={(visible) => {
                    if (visible && commitOptions.length === 0) loadCommits()
                  }}
                />
              </Form.Item>
            )}

            <Form.Item label="补充提示词">
              <Input.TextArea
                value={userPrompt}
                onChange={(e) => setUserPrompt(e.target.value)}
                placeholder="输入补充的提示词，帮助AI更精准地定位问题..."
                rows={4}
                maxLength={2000}
                showCount
              />
            </Form.Item>

            <Form.Item>
              <Space>
                <Button
                  type="primary"
                  icon={<RobotOutlined />}
                  onClick={handleStartDiagnosis}
                  loading={isStreaming}
                  disabled={isStreaming}
                >
                  {isStreaming ? '诊断中...' : '开始诊断'}
                </Button>
                {streamContent && !isStreaming && (
                  <Button icon={<CopyOutlined />} onClick={handleCopy}>
                    复制
                  </Button>
                )}
                {streamContent && !isStreaming && (
                  <Button icon={<DownloadOutlined />} onClick={handleExport}>
                    导出
                  </Button>
                )}
              </Space>
            </Form.Item>
          </Form>

          {error && (
            <Alert
              message="诊断失败"
              description={error}
              type="error"
              showIcon
              closable
              onClose={() => setError(null)}
              style={{ marginTop: 8 }}
            />
          )}
        </div>

        <div style={{ flex: 1 }}>
          <StreamMarkdownRenderer
            content={streamContent}
            isStreaming={isStreaming}
            meta={meta}
            summary={summary}
          />
        </div>
      </div>
    </Modal>
  )
}

export default IssueDiagnosisModal
