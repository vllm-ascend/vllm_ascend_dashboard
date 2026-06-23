import { useState, useCallback, useEffect } from 'react'
import {
  Card,
  Form,
  Select,
  Input,
  Button,
  Space,
  Alert,
  message,
  Typography,
  Upload,
  Tabs,
  Divider,
} from 'antd'
import {
  RobotOutlined,
  CopyOutlined,
  DownloadOutlined,
  SearchOutlined,
  UploadOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import StreamMarkdownRenderer from '../components/StreamMarkdownRenderer'
import {
  IssueDiagnosisRequest,
  CIJobOption,
  CommitOption,
  getFailedCIJobs,
  getRecentCommits,
  streamDiagnosis,
} from '../services/issueDiagnosis'

const { Title, Text } = Typography

function IssueDiagnosis() {
  const [dataSourceType, setDataSourceType] = useState<string>('ci_job')
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null)
  const [selectedCommitSha, setSelectedCommitSha] = useState<string | null>(null)
  const [userPrompt, setUserPrompt] = useState('')
  const [logContent, setLogContent] = useState('')
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
    if (dataSourceType === 'ci_job' && ciJobOptions.length === 0) {
      loadCIJobs()
    }
  }, [dataSourceType])

  const handleDataSourceTypeChange = (type: string) => {
    setDataSourceType(type)
    setSelectedJobId(null)
    setSelectedCommitSha(null)
    if (type === 'ci_job') loadCIJobs()
    if (type === 'commit') loadCommits()
  }

  const handleLogFileUpload = (file: File) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      const text = e.target?.result as string
      setLogContent(text)
      message.success(`已加载日志文件 (${text.length} 字符)`)
    }
    reader.readAsText(file)
    return false
  }

  const handleStartDiagnosis = async () => {
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

    const request: IssueDiagnosisRequest = {
      data_source_type: hasDataSource ? (dataSourceType as 'ci_job' | 'commit' | 'manual') : 'manual',
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

  const handleReset = () => {
    setStreamContent('')
    setMeta(null)
    setSummary(null)
    setError(null)
    setUserPrompt('')
    setLogContent('')
  }

  return (
    <div className="stripe-ci-page">
      <div className="stripe-page-header">
        <Title level={3} className="stripe-page-title">
          <SearchOutlined style={{ marginRight: 8 }} />
          问题自动定位
        </Title>
        <Text className="stripe-page-description">
          通过 AI 智能分析，快速定位问题根因并给出改进建议
        </Text>
      </div>

      <div style={{ display: 'flex', gap: 24, marginTop: 16 }}>
        {/* 左栏：配置面板 */}
        <Card
          title="诊断配置"
          style={{ width: 420, flexShrink: 0 }}
          extra={
            streamContent ? (
              <Space size="small">
                <Button icon={<CopyOutlined />} size="small" onClick={handleCopy}>复制</Button>
                <Button icon={<DownloadOutlined />} size="small" onClick={handleExport}>导出</Button>
                <Button size="small" onClick={handleReset}>重置</Button>
              </Space>
            ) : null
          }
        >
          <Form layout="vertical">
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
                    label: `#${j.job_id} ${j.workflow_name} - ${j.job_name}`,
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

            <Divider orientation="left" style={{ marginTop: 8, marginBottom: 12 }}>
              <Space size={4}>
                <FileTextOutlined />
                <span style={{ fontSize: 13 }}>提示词与日志</span>
              </Space>
            </Divider>

            <Tabs
              type="card"
              size="small"
              items={[
                {
                  key: 'prompt',
                  label: '提示词',
                  children: (
                    <Input.TextArea
                      value={userPrompt}
                      onChange={(e) => setUserPrompt(e.target.value)}
                      placeholder="输入补充提示词，描述你遇到的问题或你想了解的方向..."
                      rows={6}
                      maxLength={4000}
                      showCount
                    />
                  ),
                },
                {
                  key: 'log',
                  label: '日志提交',
                  children: (
                    <Space direction="vertical" style={{ width: '100%' }} size="middle">
                      <Upload
                        accept=".log,.txt,.json,.yaml,.yml,.xml,.csv"
                        maxCount={1}
                        showUploadList={false}
                        beforeUpload={handleLogFileUpload}
                      >
                        <Button icon={<UploadOutlined />} block>
                          上传日志文件
                        </Button>
                      </Upload>
                      <Input.TextArea
                        value={logContent}
                        onChange={(e) => setLogContent(e.target.value)}
                        placeholder="或直接粘贴日志内容..."
                        rows={6}
                        maxLength={50000}
                        showCount
                      />
                      {logContent && (
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          已输入 {logContent.length} 字符
                        </Text>
                      )}
                    </Space>
                  ),
                },
              ]}
            />

            <Form.Item style={{ marginTop: 16 }}>
              <Button
                type="primary"
                icon={<RobotOutlined />}
                onClick={handleStartDiagnosis}
                loading={isStreaming}
                disabled={isStreaming}
                block
                size="large"
              >
                {isStreaming ? '诊断中...' : '开始诊断'}
              </Button>
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
        </Card>

        {/* 右栏：结果展示 */}
        <Card
          title="AI 分析结果"
          style={{ flex: 1, minHeight: 600 }}
        >
          <StreamMarkdownRenderer
            content={streamContent}
            isStreaming={isStreaming}
            meta={meta}
            summary={summary}
          />
        </Card>
      </div>
    </div>
  )
}

export default IssueDiagnosis
