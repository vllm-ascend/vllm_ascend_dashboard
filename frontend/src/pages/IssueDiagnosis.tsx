import { useState, useCallback, useEffect } from 'react'
import {
  Card,
  Form,
  Select,
  Input,
  Button,
  Space,
  Alert,
  Typography,
  Upload,
  Tabs,
  Divider,
  Table,
  Tag,
  Modal,
  Checkbox,
  Row,
  Col,
  Statistic,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  RobotOutlined,
  CopyOutlined,
  DownloadOutlined,
  SearchOutlined,
  UploadOutlined,
  FileTextOutlined,
  HeartOutlined,
  EyeOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import StreamMarkdownRenderer from '../components/StreamMarkdownRenderer'
import { useIssueDiagnosis } from '../hooks/useIssueDiagnosis'
import {
  getDiagnosisHistory,
  getDiagnosisStats,
  getDiagnosisDetail,
  toggleDiagnosisLike,
  type DiagnosisHistoryItem,
  type DiagnosisStats,
} from '../services/issueDiagnosis'

const { Title, Text } = Typography

const TYPE_TAG_MAP: Record<string, { color: string; label: string }> = {
  pr_pipeline: { color: 'purple', label: 'PR流水线' },
  ci_job: { color: 'blue', label: 'Nightly Job' },
  manual: { color: 'default', label: '手动' },
}

function formatDuration(seconds: number | null | undefined) {
  if (seconds == null) return '-'
  return `${seconds.toFixed(1)}s`
}

function formatSuccessRate(rate: number | null | undefined) {
  if (rate == null) return '0%'
  const pct = rate > 1 ? rate : rate * 100
  return `${pct.toFixed(1)}%`
}

function IssueDiagnosis() {
  const {
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
    handleDataSourceTypeChange,
    setPrNumber,
    setSelectedJobId,
    setUserPrompt,
    setLogContent,
    setFollowUpQuestion,
    handleStartDiagnosis,
    handleFollowUp,
    handleCopy,
    handleExport,
    handleReset,
    handleLogFileUpload,
    handleLike,
    clearError,
  } = useIssueDiagnosis()

  const [activeTab, setActiveTab] = useState('diagnosis')
  const [historyList, setHistoryList] = useState<DiagnosisHistoryItem[]>([])
  const [historyTotal, setHistoryTotal] = useState(0)
  const [historyPage, setHistoryPage] = useState(1)
  const [historyStats, setHistoryStats] = useState<DiagnosisStats | null>(null)
  const [historyFilter, setHistoryFilter] = useState<string>('')
  const [likedOnly, setLikedOnly] = useState(false)
  const [reportModal, setReportModal] = useState<{ visible: boolean; content: string; title: string }>({ visible: false, content: '', title: '' })
  const [historyLoading, setHistoryLoading] = useState(false)

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    try {
      const [listRes, stats] = await Promise.all([
        getDiagnosisHistory({
          page: historyPage,
          page_size: 20,
          diagnosis_type: historyFilter || undefined,
          liked_only: likedOnly,
        }),
        getDiagnosisStats(),
      ])
      setHistoryList(listRes.items)
      setHistoryTotal(listRes.total)
      setHistoryStats(stats)
    } catch {
      message.error('加载历史记录失败')
    } finally {
      setHistoryLoading(false)
    }
  }, [historyPage, historyFilter, likedOnly])

  useEffect(() => {
    if (activeTab === 'history') loadHistory()
  }, [activeTab, loadHistory])

  const handleToggleLike = useCallback(async (id: number) => {
    try {
      const res = await toggleDiagnosisLike(id)
      setHistoryList(prev => prev.map(item => item.id === id ? { ...item, is_liked: res.is_liked, like_count: res.like_count } : item))
      setHistoryStats(prev => prev ? { ...prev, liked_count: prev.liked_count + (res.is_liked ? 1 : -1) } : prev)
    } catch {
      message.error('操作失败')
    }
  }, [])

  const handleViewReport = useCallback(async (item: DiagnosisHistoryItem) => {
    try {
      message.loading({ content: '加载报告中...', key: 'report', duration: 0 })
      const detail = await getDiagnosisDetail(item.id)
      message.destroy('report')
      setReportModal({
        visible: true,
        content: detail.report_content,
        title: `${TYPE_TAG_MAP[item.diagnosis_type]?.label || item.diagnosis_type} - ${item.target_label || item.target_id}`,
      })
    } catch {
      message.destroy('report')
      message.error('加载报告失败')
    }
  }, [])

  const closeReportModal = useCallback(() => {
    setReportModal(prev => ({ ...prev, visible: false }))
  }, [])

  const columns: ColumnsType<DiagnosisHistoryItem> = [
    {
      title: '类型',
      dataIndex: 'diagnosis_type',
      key: 'diagnosis_type',
      width: 120,
      render: (type: string) => {
        const info = TYPE_TAG_MAP[type] || { color: 'default', label: type }
        return <Tag color={info.color}>{info.label}</Tag>
      },
    },
    {
      title: '问题标识',
      key: 'target',
      render: (_: any, record: DiagnosisHistoryItem) => (
        <span>{record.target_label || record.target_id}</span>
      ),
    },
    {
      title: '定位人',
      dataIndex: 'username',
      key: 'username',
      width: 100,
    },
    {
      title: '定位时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (val: string) => new Date(val).toLocaleString(),
    },
    {
      title: '耗时',
      dataIndex: 'duration_seconds',
      key: 'duration_seconds',
      width: 100,
      render: (val: number) => formatDuration(val),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={status === 'success' ? 'green' : 'red'}>
          {status === 'success' ? '成功' : '失败'}
        </Tag>
      ),
    },
    {
      title: '点赞',
      key: 'like',
      width: 100,
      render: (_: any, record: DiagnosisHistoryItem) => (
        <Space>
          <Button
            type="text"
            size="small"
            icon={<HeartOutlined style={{ color: record.is_liked ? '#ff4d4f' : undefined }} />}
            onClick={() => handleToggleLike(record.id)}
          />
          <span>{record.like_count}</span>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: any, record: DiagnosisHistoryItem) => (
        <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleViewReport(record)}>
          查看报告
        </Button>
      ),
    },
  ]

  return (
    <div className="stripe-ci-page">
      <div className="stripe-page-header">
        <Title level={3} className="stripe-page-title">
          <SearchOutlined style={{ marginRight: 8 }} />
          问题自动定位
        </Title>
        <Text className="stripe-page-description">
          输入 PR 编号或选择 Nightly Job，AI 智能分析问题根因并给出改进建议
        </Text>
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        style={{ marginTop: 16 }}
        items={[
          {
            key: 'diagnosis',
            label: '问题诊断',
            children: (
              <div style={{ display: 'flex', gap: 24 }}>
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
                    <Form.Item label="诊断类型">
                      <Select
                        value={dataSourceType}
                        onChange={handleDataSourceTypeChange}
                        options={[
                          { label: 'PR 流水线诊断', value: 'pr_pipeline' },
                          { label: 'Nightly Job 失败诊断', value: 'ci_job' },
                          { label: '手动输入', value: 'manual' },
                        ]}
                      />
                    </Form.Item>

                    {dataSourceType === 'pr_pipeline' && (
                      <Form.Item label="PR 编号">
                        <Input
                          type="number"
                          value={prNumber ?? ''}
                          onChange={(e) => setPrNumber(e.target.value ? Number(e.target.value) : null)}
                          placeholder="请输入 PR 编号，如 154"
                          size="large"
                        />
                      </Form.Item>
                    )}

                    {dataSourceType === 'ci_job' && (
                      <Form.Item label="选择 Nightly Job">
                        <Select
                          value={selectedJobId}
                          onChange={setSelectedJobId}
                          loading={loadingJobs}
                          placeholder="请选择一个失败的 Job"
                          showSearch
                          optionFilterProp="label"
                          options={ciJobOptions.map(j => ({
                            value: j.job_id,
                            label: `#${j.job_id} ${j.workflow_name} - ${j.job_name}`,
                          }))}
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
                      onClose={clearError}
                      style={{ marginTop: 8 }}
                    />
                  )}
                </Card>

                <Card title="AI 分析结果" style={{ flex: 1, minHeight: 600 }} extra={
                  historyId && !isStreaming && streamContent ? (
                    <Button
                      type={isLiked ? 'primary' : 'default'}
                      icon={<HeartOutlined />}
                      onClick={handleLike}
                      size="small"
                    >
                      {isLiked ? '已赞' : '点赞'}
                    </Button>
                  ) : null
                }>
                  <div style={{ height: 500 }}>
                    <StreamMarkdownRenderer
                      content={streamContent}
                      messages={conversation}
                      isStreaming={isStreaming}
                      meta={meta}
                      summary={summary}
                    />
                  </div>
                  {streamContent && (
                    <>
                      <Divider style={{ margin: '16px 0 12px' }} />
                      <Space.Compact style={{ width: '100%' }}>
                        <Input.TextArea
                          value={followUpQuestion}
                          onChange={event => setFollowUpQuestion(event.target.value)}
                          onPressEnter={event => {
                            if (!event.shiftKey) {
                              event.preventDefault()
                              handleFollowUp()
                            }
                          }}
                          placeholder="继续追问 AI 分析结果，Enter 发送，Shift+Enter 换行"
                          autoSize={{ minRows: 2, maxRows: 5 }}
                          disabled={isStreaming}
                        />
                        <Button
                          type="primary"
                          onClick={handleFollowUp}
                          loading={isStreaming}
                          disabled={isStreaming || !followUpQuestion.trim()}
                        >
                          追问
                        </Button>
                      </Space.Compact>
                    </>
                  )}
                </Card>
              </div>
            ),
          },
          {
            key: 'history',
            label: '历史记录',
            children: (
              <div>
                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={4}><Card><Statistic title="总诊断数" value={historyStats?.total ?? 0} /></Card></Col>
                  <Col span={4}><Card><Statistic title="成功率" value={formatSuccessRate(historyStats?.success_rate)} /></Card></Col>
                  <Col span={4}><Card><Statistic title="点赞数" value={historyStats?.liked_count ?? 0} /></Card></Col>
                  <Col span={4}><Card><Statistic title="PR诊断" value={historyStats?.pr_pipeline_count ?? 0} /></Card></Col>
                  <Col span={4}><Card><Statistic title="Job诊断" value={historyStats?.ci_job_count ?? 0} /></Card></Col>
                </Row>

                <Card>
                  <Space style={{ marginBottom: 16 }}>
                    <Select
                      value={historyFilter}
                      onChange={(val: string) => { setHistoryFilter(val); setHistoryPage(1) }}
                      style={{ width: 160 }}
                      options={[
                        { label: '全部', value: '' },
                        { label: 'PR流水线', value: 'pr_pipeline' },
                        { label: 'Nightly Job', value: 'ci_job' },
                        { label: '手动', value: 'manual' },
                      ]}
                    />
                    <Checkbox
                      checked={likedOnly}
                      onChange={(e) => { setLikedOnly(e.target.checked); setHistoryPage(1) }}
                    >
                      仅看点赞
                    </Checkbox>
                  </Space>

                  <Table
                    dataSource={historyList}
                    columns={columns}
                    loading={historyLoading}
                    rowKey="id"
                    pagination={{
                      current: historyPage,
                      total: historyTotal,
                      pageSize: 20,
                      onChange: (page) => setHistoryPage(page),
                      showTotal: (t) => `共 ${t} 条`,
                    }}
                  />
                </Card>
              </div>
            ),
          },
        ]}
      />

      <Modal
        title={reportModal.title}
        open={reportModal.visible}
        onCancel={closeReportModal}
        footer={[<Button key="close" onClick={closeReportModal}>关闭</Button>]}
        width={900}
      >
        <div style={{ maxHeight: '70vh', overflowY: 'auto' }}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{reportModal.content}</ReactMarkdown>
        </div>
      </Modal>
    </div>
  )
}

export default IssueDiagnosis
