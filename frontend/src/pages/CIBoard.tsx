import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Card, Table, Space, Statistic, Row, Col, Typography, Tabs, Button, message, Modal } from 'antd'
import {
  GithubOutlined,
  BarChartOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import { useCIStats, useRuns, useCITrends } from '../hooks/useCI'
import { useAnalyzeBatch } from '../hooks/useFailureAnalysis'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import { formatTimezone, fromTimezoneNow } from '../utils/timezone'
import api from '../services/api'
import { renderStatusTag, renderConclusionTag, formatDuration, renderHardwareTag } from '../utils/ciRenderers'
import { CIResult } from '../services/ci'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer } from 'recharts'
import JobBoard from './JobBoard'
import './CIBoard.css'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const { Text, Title } = Typography

interface WorkflowConfig {
  id: number
  workflow_name: string
  workflow_file: string
  hardware: string
  enabled: boolean
  last_sync_at: string | null
}

function CIBoard() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // 表格筛选状态
  const [workflowFilter, setWorkflowFilter] = useState<string[]>([])
  const [hardwareFilter, setHardwareFilter] = useState<string[]>([])
  const [conclusionFilter, setConclusionFilter] = useState<string[]>([])
  const [enabledWorkflows, setEnabledWorkflows] = useState<WorkflowConfig[]>([])

  // 根据 URL 参数设置默认 Tab
  const [activeTab, setActiveTab] = useState(() => {
    return searchParams.get('tab') === 'job' ? 'job' : 'workflow'
  })

  // 获取启用的 workflow 列表
  useEffect(() => {
    const fetchEnabledWorkflows = async () => {
      try {
        const response = await api.get<WorkflowConfig[]>('/workflows?enabled=true')
        setEnabledWorkflows(response.data)
      } catch (error) {
        console.error('Failed to fetch workflows:', error)
      }
    }
    fetchEnabledWorkflows()
  }, [])

  const { data: stats, isLoading: statsLoading } = useCIStats({
    workflow_name: workflowFilter.length > 0 ? workflowFilter[0] : undefined,
    hardware: hardwareFilter.length > 0 ? hardwareFilter[0] : undefined,
  })

  const { data: runs, isLoading: runsLoading } = useRuns({
    workflow_name: workflowFilter.length > 0 ? workflowFilter[0] : undefined,
    hardware: hardwareFilter.length > 0 ? hardwareFilter[0] : undefined,
    limit: 50,
  })

  const { data: trends } = useCITrends({
    days: 30,
    workflow_name: workflowFilter.length > 0 ? workflowFilter[0] : undefined,
    hardware: hardwareFilter.length > 0 ? hardwareFilter[0] : undefined,
  })

  const analyzeBatchMutation = useAnalyzeBatch()

  const handleBatchAnalyze = () => {
    Modal.confirm({
      title: '批量失败分析',
      content: '确定要对最近 7 天的失败 Job 进行批量 AI 分析吗？这可能需要较长时间。',
      okText: '确认',
      cancelText: '取消',
      onOk: () => {
        analyzeBatchMutation.mutate({ daysBack: 7 }, {
          onSuccess: (data) => {
            message.success(data.message || '批量分析完成')
          },
          onError: (error: any) => {
            message.error((error as any)?.response?.data?.detail || '批量分析失败')
          },
        })
      },
    })
  }

  // 表格列定义
  const columns = [
    {
      title: 'Workflow',
      dataIndex: 'workflow_name',
      key: 'workflow_name',
      width: 200,
      ellipsis: true,
      filters: enabledWorkflows.map((wf) => ({
        text: wf.workflow_name,
        value: wf.workflow_name,
      })),
      filteredValue: workflowFilter,
      onFilter: (value: any, record: any) => record.workflow_name === value,
      render: (text: string, record: CIResult) => (
        <Space size={4}>
          <span style={{ fontWeight: 500 }}>{text}</span>
          {record.github_html_url && (
            <a
              href={record.github_html_url}
              target="_blank"
              rel="noopener noreferrer"
              title="在 GitHub 上查看"
            >
              <GithubOutlined />
            </a>
          )}
        </Space>
      ),
    },
    {
      title: '开始时间',
      dataIndex: 'started_at',
      key: 'started_at',
      width: 180,
      sorter: (a: any, b: any) => {
        if (!a.started_at) return -1
        if (!b.started_at) return 1
        return new Date(b.started_at).getTime() - new Date(a.started_at).getTime()
      },
      render: (startedAt: string | null) => {
        if (!startedAt) return '-'
        return (
          <Space direction="vertical" size={0}>
            <Text strong>{formatTimezone(startedAt, 'YYYY-MM-DD HH:mm:ss')}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {fromTimezoneNow(startedAt)}
            </Text>
          </Space>
        )
      },
    },
    {
      title: '硬件',
      dataIndex: 'hardware',
      key: 'hardware',
      width: 100,
      filters: Array.from(new Set(enabledWorkflows.map((wf) => wf.hardware)))
        .filter(Boolean)
        .map((hw) => ({
          text: hw,
          value: hw,
        })),
      filteredValue: hardwareFilter,
      onFilter: (value: any, record: any) => record.hardware === value,
      render: renderHardwareTag,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: renderStatusTag,
    },
    {
      title: '结果',
      dataIndex: 'conclusion',
      key: 'conclusion',
      width: 100,
      filters: [
        { text: '成功', value: 'success' },
        { text: '失败', value: 'failure' },
        { text: '取消', value: 'cancelled' },
        { text: '进行中', value: 'in_progress' },
        { text: '等待中', value: 'queued' },
        { text: '其他', value: 'other' },
      ],
      filteredValue: conclusionFilter,
      onFilter: (value: any, record: any) => {
        if (value === 'other') {
          return record.conclusion !== 'success' && record.conclusion !== 'failure' && record.conclusion !== 'cancelled'
        }
        return record.conclusion === value
      },
      render: renderConclusionTag,
    },
    {
      title: '时长',
      dataIndex: 'duration_seconds',
      key: 'duration_seconds',
      width: 90,
      render: formatDuration,
    },
  ]

  return (
    <div className="stripe-ci-page">
      {/* 页面标题 */}
      <div className="stripe-page-header">
        <Title level={3} className="stripe-page-title">
          CI 看板
        </Title>
        <Text className="stripe-page-description">
          查看 CI 运行状态和统计信息
        </Text>
      </div>

      <Tabs
          activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'workflow',
            label: (
              <Space>
                <GithubOutlined />
                <span>Workflow 运行</span>
              </Space>
            ),
            children: (
              <div>
                {/* 页面标题和操作区 */}
                <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <Title level={3} style={{ margin: 0 }}>
                      Workflow 运行
                    </Title>
                    <Text type="secondary">
                      展示各 Workflow 的运行状态和趋势
                    </Text>
                  </div>
                  <Button
                    icon={<RobotOutlined />}
                    loading={analyzeBatchMutation.isPending}
                    onClick={handleBatchAnalyze}
                  >
                    批量失败分析
                  </Button>
                </div>

                {/* 统计卡片 */}
                <Row gutter={16} style={{ marginBottom: 24 }}>
                  <Col span={8}>
                    <Card loading={statsLoading}>
                      <Statistic
                        title="总运行次数"
                        value={stats?.total_runs || 0}
                        suffix="次"
                      />
                      {stats?.last_7_days && (
                        <div style={{ fontSize: 12, color: '#999', marginTop: 8 }}>
                          近 7 天：{stats.last_7_days.runs}次
                        </div>
                      )}
                    </Card>
                  </Col>
                  <Col span={8}>
                    <Card loading={statsLoading}>
                      <Statistic
                        title="成功率"
                        value={stats?.success_rate || 0}
                        suffix="%"
                        valueStyle={{
                          color: (stats?.success_rate || 0) >= 90 ? '#3f8600' :
                                 (stats?.success_rate || 0) >= 70 ? '#1890ff' : '#cf1322',
                        }}
                      />
                      {stats?.last_7_days && (
                        <div style={{ fontSize: 12, color: '#999', marginTop: 8 }}>
                          近 7 天：{Math.round(stats.last_7_days.success_rate)}%
                        </div>
                      )}
                    </Card>
                  </Col>
                  <Col span={8}>
                    <Card loading={statsLoading}>
                      <Statistic
                        title="平均时长"
                        value={stats?.avg_duration_seconds ? Math.round(stats.avg_duration_seconds / 60) : 0}
                        suffix="分钟"
                      />
                      {stats?.last_7_days && (
                        <div style={{ fontSize: 12, color: '#999', marginTop: 8 }}>
                          近 7 天平均：{stats.last_7_days.avg_duration_seconds ? Math.round(stats.last_7_days.avg_duration_seconds / 60) : 0}分钟
                        </div>
                      )}
                    </Card>
                  </Col>
                </Row>

                {/* 趋势图表 */}
                {trends && trends.length > 0 && (
                  <Row gutter={16} style={{ marginBottom: 24 }}>
                    <Col span={12}>
                      <Card title="时长变化趋势（近 30 天）">
                        <ResponsiveContainer width="100%" height={220}>
                          <LineChart data={trends.map(t => ({
                            date: dayjs(t.date).format('MM-DD'),
                            duration: t.max_duration_seconds ? Math.round(t.max_duration_seconds / 60) : null,
                          }))}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                            <YAxis tickFormatter={(v: number) => `${v}m`} tick={{ fontSize: 11 }} />
                            <RechartsTooltip formatter={(v: number) => `${v} 分钟`} />
                            <Line type="monotone" dataKey="duration" stroke="#1677ff" strokeWidth={2} name="最大时长" dot={{ r: 3 }} connectNulls />
                          </LineChart>
                        </ResponsiveContainer>
                      </Card>
                    </Col>
                    <Col span={12}>
                      <Card title="成功率变化趋势（近 30 天）">
                        <ResponsiveContainer width="100%" height={220}>
                          <LineChart data={trends.map(t => ({
                            date: dayjs(t.date).format('MM-DD'),
                            rate: t.success_rate,
                          }))}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                            <YAxis domain={[0, 100]} tickFormatter={(v: number) => `${v}%`} tick={{ fontSize: 11 }} />
                            <RechartsTooltip formatter={(v: number) => `${v}%`} />
                            <Line type="monotone" dataKey="rate" stroke="#52c41a" strokeWidth={2} name="成功率" dot={{ r: 3 }} />
                          </LineChart>
                        </ResponsiveContainer>
                      </Card>
                    </Col>
                  </Row>
                )}

                {/* 运行记录表格 */}
                <Card title="运行记录">
                  <Table
                    columns={columns}
                    dataSource={runs}
                    loading={runsLoading}
                    rowKey="id"
                    pagination={{
                      pageSize: 20,
                      showSizeChanger: false,
                    }}
                    scroll={{ x: 800 }}
                    onRow={(record: CIResult) => ({
                      onClick: () => navigate(`/ci/runs/${record.run_id}`),
                      style: { cursor: 'pointer' },
                    })}
                    onChange={(_, filters) => {
                      if (filters.workflow_name) {
                        setWorkflowFilter(filters.workflow_name as string[])
                      } else {
                        setWorkflowFilter([])
                      }
                      if (filters.hardware) {
                        setHardwareFilter(filters.hardware as string[])
                      } else {
                        setHardwareFilter([])
                      }
                      if (filters.conclusion) {
                        setConclusionFilter(filters.conclusion as string[])
                      } else {
                        setConclusionFilter([])
                      }
                    }}
                  />
                </Card>
              </div>
            ),
          },
          {
            key: 'job',
            label: (
              <Space>
                <BarChartOutlined />
                <span>Job 统计</span>
              </Space>
            ),
            children: <JobBoard />,
          },
        ]}
      />
    </div>
  )
}

export default CIBoard
