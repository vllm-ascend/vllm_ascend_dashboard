import { useState } from 'react'
import {
  Card, Table, Space, Statistic, Row, Col, Typography, Tabs, Tag, Button, message, Modal, Input, Select, Progress, Tooltip, Empty,
} from 'antd'
import {
  BugOutlined, CheckCircleOutlined, WarningOutlined, ClockCircleOutlined,
  SyncOutlined, DashboardOutlined, BarChartOutlined, TeamOutlined, ApartmentOutlined,
} from '@ant-design/icons'
import { useTestOverview, useTestCases, useFlakyCases, useFailureBreakdown, useOwnerMatrix, useModuleHealth, useTriggerSync, useTestSuites } from '../hooks/useTestBoard'
import type { TestCaseItem, FlakyCaseDetail, FailureBreakdown, OwnerMatrixItem, ModuleHealthItem, TestSuiteItem } from '../services/testBoard'
import './TestObservabilityDashboard.css'

const { Text, Title } = Typography

function getHealthColor(level: string | null): string {
  if (level === 'A') return '#3f8600'
  if (level === 'B') return '#1890ff'
  if (level === 'C') return '#faad14'
  if (level === 'D') return '#cf1322'
  return '#d9d9d9'
}

function getResultTag(result: string | null) {
  if (result === 'passed') return <Tag color="success">通过</Tag>
  if (result === 'failed') return <Tag color="error">失败</Tag>
  if (result === 'error') return <Tag color="error">错误</Tag>
  if (result === 'skipped') return <Tag color="default">跳过</Tag>
  return <Tag>{result || '未知'}</Tag>
}

function getGranularityTag(granularity: string) {
  if (granularity === 'function_level') return <Tag color="green">函数级</Tag>
  if (granularity === 'file_level') return <Tag color="blue">文件级</Tag>
  if (granularity === 'step_level') return <Tag color="orange">步骤级</Tag>
  return <Tag>{granularity}</Tag>
}

function TestObservabilityDashboard() {
  const [activeTab, setActiveTab] = useState('overview')
  const { data: overview, isLoading: overviewLoading } = useTestOverview(7)
  const { data: suites, isLoading: suitesLoading } = useTestSuites()
  const syncMutation = useTriggerSync()

  const [casePage, setCasePage] = useState(1)
  const [caseFilters, setCaseFilters] = useState<Record<string, string | undefined>>({})
  const { data: casesData, isLoading: casesLoading } = useTestCases({
    ...caseFilters,
    page: casePage,
    per_page: 20,
  })

  const [flakyPage, setFlakyPage] = useState(1)
  const { data: flakyData, isLoading: flakyLoading } = useFlakyCases({ page: flakyPage, per_page: 20 })

  const { data: breakdown, isLoading: breakdownLoading } = useFailureBreakdown({ days: 30 })
  const { data: owners, isLoading: ownersLoading } = useOwnerMatrix()
  const { data: modules, isLoading: modulesLoading } = useModuleHealth()

  const handleSync = () => {
    Modal.confirm({
      title: '同步测试数据',
      content: '确定要从 CI 结果解析最近 7 天的测试数据吗？',
      okText: '确认',
      cancelText: '取消',
      onOk: () => {
        syncMutation.mutate({ days_back: 7, force: false }, {
          onSuccess: (data) => message.success(data.message || '同步完成'),
          onError: () => message.error('同步失败'),
        })
      },
    })
  }

  const caseColumns = [
    {
      title: '用例名称',
      dataIndex: 'test_name',
      key: 'test_name',
      width: 240,
      ellipsis: true,
      render: (name: string, record: TestCaseItem) => (
        <Space size={4}>
          <span style={{ fontWeight: 500 }}>{name}</span>
          {record.is_flaky && <Tag color="volcano">Flaky</Tag>}
        </Space>
      ),
    },
    {
      title: '套件',
      dataIndex: 'test_suite',
      key: 'test_suite',
      width: 150,
      ellipsis: true,
    },
    {
      title: '硬件',
      dataIndex: 'hardware',
      key: 'hardware',
      width: 80,
      render: (hw: string | null) => hw ? <Tag>{hw}</Tag> : '-',
    },
    {
      title: '健康分',
      dataIndex: 'health_score',
      key: 'health_score',
      width: 80,
      sorter: true,
      render: (score: number | null, record: TestCaseItem) => (
        <Tooltip title={`等级: ${record.health_level || '-'}`}>
          <span style={{ color: getHealthColor(record.health_level), fontWeight: 600 }}>
            {score ? Math.round(score) : '-'}
          </span>
        </Tooltip>
      ),
    },
    {
      title: '通过率',
      dataIndex: 'pass_rate_7d',
      key: 'pass_rate_7d',
      width: 80,
      render: (rate: number | null) => rate ? `${Math.round(rate * 100)}%` : '-',
    },
    {
      title: 'Flaky率',
      dataIndex: 'flaky_rate',
      key: 'flaky_rate',
      width: 80,
      render: (rate: number) => rate > 0 ? <span style={{ color: '#cf1322' }}>{Math.round(rate * 100)}%</span> : '0%',
    },
    {
      title: '粒度',
      dataIndex: 'data_granularity',
      key: 'data_granularity',
      width: 80,
      render: getGranularityTag,
    },
    {
      title: '最近结果',
      dataIndex: 'last_result',
      key: 'last_result',
      width: 100,
      render: getResultTag,
    },
    {
      title: '负责人',
      dataIndex: 'owner',
      key: 'owner',
      width: 100,
      render: (owner: string | null) => owner || <Text type="secondary">未分配</Text>,
    },
  ]

  const flakyColumns = [
    {
      title: '用例名称',
      dataIndex: 'test_name',
      key: 'test_name',
      width: 240,
      ellipsis: true,
    },
    {
      title: '套件',
      dataIndex: 'test_suite',
      key: 'test_suite',
      width: 150,
    },
    {
      title: '翻转率',
      dataIndex: 'flip_rate',
      key: 'flip_rate',
      width: 100,
      sorter: true,
      render: (rate: number) => (
        <Progress
          percent={Math.round(rate * 100)}
          size="small"
          strokeColor={rate > 0.25 ? '#cf1322' : rate > 0.1 ? '#faad14' : '#1890ff'}
          format={() => `${Math.round(rate * 100)}%`}
        />
      ),
    },
    {
      title: '翻转次数',
      dataIndex: 'flip_count',
      key: 'flip_count',
      width: 80,
    },
    {
      title: '总运行',
      dataIndex: 'total_runs',
      key: 'total_runs',
      width: 80,
    },
    {
      title: '最近结果',
      dataIndex: 'recent_results',
      key: 'recent_results',
      width: 200,
      render: (results: string[]) => (
        <Space size={2}>
          {results.slice(0, 10).map((r, i) => getResultTag(r))}
        </Space>
      ),
    },
    {
      title: '建议',
      dataIndex: 'suggested_action',
      key: 'suggested_action',
      width: 100,
      render: (action: string) => {
        if (action === '紧急修复') return <Tag color="red">{action}</Tag>
        if (action === '需要治理') return <Tag color="orange">{action}</Tag>
        return <Tag color="blue">{action}</Tag>
      },
    },
    {
      title: '负责人',
      dataIndex: 'owner',
      key: 'owner',
      width: 100,
    },
  ]

  const ownerColumns = [
    {
      title: '负责人',
      dataIndex: 'owner',
      key: 'owner',
      width: 120,
      render: (owner: string | null) => owner || '未分配',
    },
    {
      title: '模块',
      dataIndex: 'modules',
      key: 'modules',
      width: 200,
      render: (mods: string[]) => <Space>{mods.map(m => <Tag key={m}>{m}</Tag>)}</Space>,
    },
    {
      title: '用例数',
      dataIndex: 'total_cases',
      key: 'total_cases',
      width: 80,
    },
    {
      title: '7天通过率',
      dataIndex: 'pass_rate_7d',
      key: 'pass_rate_7d',
      width: 100,
      render: (rate: number | null) => rate ? `${Math.round(rate * 100)}%` : '-',
    },
    {
      title: 'Flaky',
      dataIndex: 'flaky_cases',
      key: 'flaky_cases',
      width: 80,
      render: (count: number) => count > 0 ? <Tag color="volcano">{count}</Tag> : <Tag>0</Tag>,
    },
    {
      title: '待修复',
      dataIndex: 'pending_failures',
      key: 'pending_failures',
      width: 80,
      render: (count: number) => count > 0 ? <Tag color="error">{count}</Tag> : <Tag>0</Tag>,
    },
  ]

  const moduleColumns = [
    {
      title: '模块',
      dataIndex: 'module_name',
      key: 'module_name',
      width: 150,
    },
    {
      title: '负责人',
      dataIndex: 'owner',
      key: 'owner',
      width: 120,
      render: (owner: string | null) => owner || '未分配',
    },
    {
      title: '用例数',
      dataIndex: 'total_cases',
      key: 'total_cases',
      width: 80,
    },
    {
      title: '7天通过率',
      dataIndex: 'pass_rate_7d',
      key: 'pass_rate_7d',
      width: 100,
      render: (rate: number | null) => rate ? `${Math.round(rate * 100)}%` : '-',
    },
    {
      title: '健康分',
      dataIndex: 'health_score',
      key: 'health_score',
      width: 80,
      render: (score: number | null, record: ModuleHealthItem) => (
        <span style={{ color: getHealthColor(record.health_level), fontWeight: 600 }}>
          {score ? Math.round(score) : '-'}
        </span>
      ),
    },
    {
      title: 'Flaky',
      dataIndex: 'flaky_count',
      key: 'flaky_count',
      width: 80,
      render: (count: number) => count > 0 ? <Tag color="volcano">{count}</Tag> : '0',
    },
    {
      title: '待修复',
      dataIndex: 'pending_failures',
      key: 'pending_failures',
      width: 80,
      render: (count: number) => count > 0 ? <Tag color="error">{count}</Tag> : '0',
    },
  ]

  return (
    <div className="stripe-test-board-page">
      <div className="stripe-page-header">
        <Title level={3} className="stripe-page-title">
          <DashboardOutlined className="stripe-page-icon" />
          测试看板
        </Title>
        <Text className="stripe-page-description">
          测试健康评分、Flaky 检测、失败分类与责任矩阵
        </Text>
        <div style={{ marginTop: 16 }}>
          <Button
            icon={<SyncOutlined />}
            loading={syncMutation.isPending}
            onClick={handleSync}
          >
            同步测试数据
          </Button>
        </div>
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'overview',
            label: <Space><DashboardOutlined /><span>概览</span></Space>,
            children: (
              <div>
                <Row gutter={16} style={{ marginBottom: 24 }}>
                  <Col span={6}>
                    <Card loading={overviewLoading}>
                      <Statistic
                        title="健康评分"
                        value={overview?.health_score?.overall ? Math.round(overview.health_score.overall) : 0}
                        suffix={`/ ${overview?.health_score?.level || '-'}`}
                        valueStyle={{ color: getHealthColor(overview?.health_score?.level || null) }}
                      />
                    </Card>
                  </Col>
                  <Col span={6}>
                    <Card loading={overviewLoading}>
                      <Statistic
                        title="总用例"
                        value={overview?.total_cases || 0}
                        prefix={<CheckCircleOutlined />}
                      />
                    </Card>
                  </Col>
                  <Col span={6}>
                    <Card loading={overviewLoading}>
                      <Statistic
                        title="7天通过率"
                        value={overview?.pass_rate_7d ? Math.round(overview.pass_rate_7d * 100) : 0}
                        suffix="%"
                        valueStyle={{ color: (overview?.pass_rate_7d || 0) >= 0.9 ? '#3f8600' : '#cf1322' }}
                      />
                    </Card>
                  </Col>
                  <Col span={6}>
                    <Card loading={overviewLoading}>
                      <Statistic
                        title="Flaky用例"
                        value={overview?.flaky_case_count || 0}
                        prefix={<WarningOutlined />}
                        valueStyle={{ color: (overview?.flaky_case_count || 0) > 0 ? '#cf1322' : '#3f8600' }}
                      />
                    </Card>
                  </Col>
                </Row>

                <Row gutter={16} style={{ marginBottom: 24 }}>
                  <Col span={6}>
                    <Card loading={overviewLoading}>
                      <Statistic title="需关注" value={overview?.attention_case_count || 0} prefix={<BugOutlined />} />
                    </Card>
                  </Col>
                  <Col span={6}>
                    <Card loading={overviewLoading}>
                      <Statistic
                        title="P50时长"
                        value={overview?.avg_duration_p50 ? Math.round(overview.avg_duration_p50) : 0}
                        suffix="秒"
                        prefix={<ClockCircleOutlined />}
                      />
                    </Card>
                  </Col>
                </Row>

                <Card title="套件分布" style={{ marginBottom: 24 }}>
                  {suites?.length ? (
                    <Table
                      dataSource={suites}
                      loading={suitesLoading}
                      rowKey={(r: TestSuiteItem) => `${r.suite_name}-${r.hardware}`}
                      pagination={false}
                      columns={[
                        { title: '套件', dataIndex: 'suite_name', key: 'suite_name', width: 200 },
                        { title: '硬件', dataIndex: 'hardware', key: 'hardware', width: 80, render: (hw: string | null) => hw ? <Tag>{hw}</Tag> : '-' },
                        { title: '用例数', dataIndex: 'total_cases', key: 'total_cases', width: 80 },
                        { title: '通过率', dataIndex: 'pass_rate', key: 'pass_rate', width: 80, render: (r: number) => `${Math.round(r * 100)}%` },
                        { title: '健康分', dataIndex: 'health_score', key: 'health_score', width: 80, render: (s: number | null, record: TestSuiteItem) => <span style={{ color: getHealthColor(record.health_level), fontWeight: 600 }}>{s ? Math.round(s) : '-'}</span> },
                        { title: 'Flaky', dataIndex: 'flaky_cases', key: 'flaky_cases', width: 80, render: (c: number) => c > 0 ? <Tag color="volcano">{c}</Tag> : '0' },
                      ]}
                    />
                  ) : <Empty description="暂无套件数据" />}
                </Card>

                <Card title="结果分布">
                  {overview?.result_distribution ? (
                    <Space size={8}>
                      {Object.entries(overview.result_distribution).map(([key, count]) => (
                        <Tag key={key} color={key === 'passed' ? 'success' : key === 'failed' ? 'error' : 'default'}>
                          {key}: {count}
                        </Tag>
                      ))}
                    </Space>
                  ) : <Empty description="暂无数据" />}
                </Card>
              </div>
            ),
          },
          {
            key: 'cases',
            label: <Space><CheckCircleOutlined /><span>用例</span></Space>,
            children: (
              <Card title="测试用例列表">
                <div style={{ marginBottom: 16, display: 'flex', gap: 8 }}>
                  <Select placeholder="类型" allowClear style={{ width: 120 }} onChange={(v) => setCaseFilters({ ...caseFilters, test_type: v })} />
                  <Select placeholder="套件" allowClear style={{ width: 150 }} onChange={(v) => setCaseFilters({ ...caseFilters, suite_name: v })} />
                  <Select placeholder="硬件" allowClear style={{ width: 100 }} onChange={(v) => setCaseFilters({ ...caseFilters, hardware: v })} />
                  <Select placeholder="结果" allowClear style={{ width: 100 }} onChange={(v) => setCaseFilters({ ...caseFilters, result: v })}
                    options={[
                      { label: '通过', value: 'passed' },
                      { label: '失败', value: 'failed' },
                      { label: '跳过', value: 'skipped' },
                    ]}
                  />
                  <Select placeholder="健康等级" allowClear style={{ width: 100 }} onChange={(v) => setCaseFilters({ ...caseFilters, health_level: v })}
                    options={[
                      { label: 'A (≥90)', value: 'A' },
                      { label: 'B (≥75)', value: 'B' },
                      { label: 'C (≥60)', value: 'C' },
                      { label: 'D (<60)', value: 'D' },
                    ]}
                  />
                </div>
                <Table
                  dataSource={casesData?.items || []}
                  loading={casesLoading}
                  rowKey="id"
                  columns={caseColumns}
                  pagination={{
                    current: casePage,
                    total: casesData?.total || 0,
                    pageSize: 20,
                    onChange: setCasePage,
                    showTotal: (total) => `共 ${total} 条`,
                  }}
                  scroll={{ x: 1200 }}
                />
              </Card>
            ),
          },
          {
            key: 'flaky',
            label: <Space><WarningOutlined /><span>Flaky 检测</span></Space>,
            children: (
              <Card title="Flaky 用例">
                <Table
                  dataSource={flakyData?.items || []}
                  loading={flakyLoading}
                  rowKey={(r: FlakyCaseDetail) => r.test_name}
                  columns={flakyColumns}
                  pagination={{
                    current: flakyPage,
                    total: flakyData?.total || 0,
                    pageSize: 20,
                    onChange: setFlakyPage,
                    showTotal: (total) => `共 ${total} 条`,
                  }}
                  scroll={{ x: 1200 }}
                />
              </Card>
            ),
          },
          {
            key: 'failures',
            label: <Space><BugOutlined /><span>失败分类</span></Space>,
            children: (
              <div>
                <Card title="失败分类概览" style={{ marginBottom: 24 }} loading={breakdownLoading}>
                  {breakdown ? (
                    <Row gutter={16}>
                      <Col span={6}>
                        <Statistic title="开发代码Bug" value={breakdown.product_bug} suffix={` (${Math.round(breakdown.product_bug_ratio * 100)}%)`} valueStyle={{ color: '#cf1322' }} />
                      </Col>
                      <Col span={6}>
                        <Statistic title="基础设施" value={breakdown.infrastructure} suffix={` (${Math.round(breakdown.infrastructure_ratio * 100)}%)`} valueStyle={{ color: '#faad14' }} />
                      </Col>
                      <Col span={6}>
                        <Statistic title="测试Bug" value={breakdown.test_bug} />
                      </Col>
                      <Col span={6}>
                        <Statistic title="噪音率" value={Math.round(breakdown.noise_ratio * 100)} suffix="%" valueStyle={{ color: breakdown.noise_ratio > 0.5 ? '#cf1322' : '#3f8600' }} />
                      </Col>
                    </Row>
                  ) : <Empty description="暂无数据" />}
                </Card>

                <Card title="责任矩阵" style={{ marginBottom: 24 }} loading={ownersLoading}>
                  <Table dataSource={owners || []} rowKey={(r: OwnerMatrixItem) => r.owner || 'unassigned'} columns={ownerColumns} pagination={false} scroll={{ x: 800 }} />
                </Card>

                <Card title="模块健康度" loading={modulesLoading}>
                  <Table dataSource={modules || []} rowKey={(r: ModuleHealthItem) => r.module_name} columns={moduleColumns} pagination={false} scroll={{ x: 800 }} />
                </Card>
              </div>
            ),
          },
        ]}
      />
    </div>
  )
}

export default TestObservabilityDashboard
