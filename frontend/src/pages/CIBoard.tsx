import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Card, Space, Statistic, Row, Col, Typography, Tabs, Button, message, Modal } from 'antd'
import {
  GithubOutlined,
  BarChartOutlined,
  RobotOutlined,
  ExclamationCircleOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { useCIStats, useCITrends } from '../hooks/useCI'
import { useAnalyzeBatch } from '../hooks/useFailureAnalysis'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer } from 'recharts'
import JobBoard from './JobBoard'
import DailyFailureTracking from './DailyFailureTracking'
import NightlyTestCaseConfig from './NightlyTestCaseConfig'
import WorkflowTestExecutionTable from '../components/WorkflowTestExecutionTable'
import './CIBoard.css'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const { Text, Title } = Typography

const CI_BOARD_TABS = ['workflow', 'job', 'daily-failure', 'test-case-config'] as const
type CIBoardTab = typeof CI_BOARD_TABS[number]
const CI_BOARD_TAB_STORAGE_KEY = 'ci-board-active-tab'

function isCIBoardTab(value: string | null): value is CIBoardTab {
  return value !== null && (CI_BOARD_TABS as readonly string[]).includes(value)
}

function CIBoard() {
  const [searchParams] = useSearchParams()

  // 根据 URL 参数设置默认 Tab
  const [activeTab, setActiveTab] = useState(() => {
    const requestedTab = searchParams.get('tab')
    const storedTab = typeof window !== 'undefined'
      ? window.localStorage.getItem(CI_BOARD_TAB_STORAGE_KEY)
      : null
    const tab = requestedTab || storedTab
    return isCIBoardTab(tab) ? tab : 'workflow'
  })

  useEffect(() => {
    window.localStorage.setItem(CI_BOARD_TAB_STORAGE_KEY, activeTab)
  }, [activeTab])

  const { data: stats, isLoading: statsLoading } = useCIStats()

  const { data: trends } = useCITrends({ days: 30 })

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
        onChange={(tab) => {
          if (isCIBoardTab(tab)) setActiveTab(tab)
        }}
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
                  <Space>
                    <Button
                      icon={<RobotOutlined />}
                      loading={analyzeBatchMutation.isPending}
                      onClick={handleBatchAnalyze}
                    >
                      批量失败分析
                    </Button>
                  </Space>
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
                      <Card title="最大时长变化趋势（近 30 天）">
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

                <WorkflowTestExecutionTable enabled={activeTab === 'workflow'} />

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
          {
            key: 'daily-failure',
            label: (
              <Space>
                <ExclamationCircleOutlined />
                <span>每日失败追踪</span>
              </Space>
            ),
            children: <DailyFailureTracking />,
          },
          {
            key: 'test-case-config',
            label: (
              <Space>
                <SettingOutlined />
                <span>用例配置</span>
              </Space>
            ),
            children: <NightlyTestCaseConfig />,
          },
        ]}
      />
    </div>
  )
}

export default CIBoard
