import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Table, Space, Tag, Select, Typography, Button, Tooltip } from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useJobStats, useHiddenJobsList } from '../hooks/useJobOwners'
import { useFailureAnalysisList } from '../hooks/useFailureAnalysis'
import { PROBLEM_CATEGORY_MAP } from '../services/failureAnalysis'
import { formatDuration, renderConclusionTag } from '../utils/ciRenderers'
import { formatTimezone } from '../utils/timezone'
import type { JobStats } from '../services/jobOwners'

const { Text } = Typography

const { Title } = Typography

function JobBoard() {
  const navigate = useNavigate()
  const [daysFilter, setDaysFilter] = useState<number | 'all'>(7)
  const [workflowFilter, setWorkflowFilter] = useState<string[]>([])
  const [ownerFilter, setOwnerFilter] = useState<string[]>([])
  const [conclusionFilter, setConclusionFilter] = useState<string[]>([])

  const { data: jobStats, isLoading, refetch } = useJobStats({
    days: daysFilter,
    workflow_name: workflowFilter.length > 0 ? workflowFilter[0] : undefined,
  })

  const { data: hiddenJobsList } = useHiddenJobsList()
  const { data: analysisData } = useFailureAnalysisList({ days_back: daysFilter === 'all' ? 90 : (daysFilter as number) })

  // 构建隐藏 job 的集合
  const hiddenJobs = new Set(
    hiddenJobsList?.filter(v => v.is_hidden).map(v => `${v.workflow_name}-${v.job_name}`) || []
  )

  const categoryMap = new Map<string, string>()
  if (analysisData?.items) {
    for (const item of analysisData.items) {
      if (item.problem_category) {
        const key = `${item.workflow_name}-${item.job_name}`
        categoryMap.set(key, item.problem_category)
      }
    }
  }

  // 过滤掉已隐藏的 job
  const filteredJobStats = jobStats?.filter(item => {
    // 检查是否在隐藏列表中
    if (hiddenJobs.has(`${item.workflow_name}-${item.job_name}`)) {
      return false
    }
    return true
  }) || []

  // 从 jobStats 中提取唯一的 workflow 名称作为过滤选项（这样只会显示有数据的启用 workflow）
  const workflowOptions = Array.from(new Set(filteredJobStats.map(item => item.workflow_name)))

  // 表格列定义
  const columns = [
    {
      title: 'Workflow',
      dataIndex: 'workflow_name',
      key: 'workflow_name',
      width: 180,
      filters: workflowOptions.map((wf) => ({
        text: wf,
        value: wf,
      })),
      filteredValue: workflowFilter,
      onFilter: (value: any, record: JobStats) => record.workflow_name === value,
      render: (text: string) => <Tag color="blue">{text}</Tag>,
    },
    {
      title: 'Job 名称',
      dataIndex: 'job_name',
      key: 'job_name',
      width: 250,
      ellipsis: true,
      render: (text: string, record: JobStats) => (
        <Tooltip
          title={
            <div>
              <div><strong>Job:</strong> {text}</div>
              {record.display_name && <div><strong>显示名:</strong> {record.display_name}</div>}
            </div>
          }
          placement="topLeft"
        >
          <div style={{ maxWidth: 230 }}>
            <Space direction="vertical" size={0}>
              <Text strong ellipsis>{text}</Text>
              {record.display_name && (
                <Text style={{ fontSize: 12, color: '#1890ff', fontWeight: 500 }} ellipsis>
                  {record.display_name}
                </Text>
              )}
            </Space>
          </div>
        </Tooltip>
      ),
    },
    {
      title: '责任人',
      dataIndex: 'owner',
      key: 'owner',
      width: 120,
      filters: Array.from(new Set(filteredJobStats.map(item => item.owner || '未配置'))).map((owner) => ({
        text: owner,
        value: owner,
      })),
      filteredValue: ownerFilter,
      onFilter: (value: any, record: JobStats) => (record.owner || '未配置') === value,
      render: (owner: string | null, record: JobStats) => {
        if (!owner) return <Text type="secondary">未配置</Text>
        return (
          <Space direction="vertical" size={0}>
            <Tag color="green">{owner}</Tag>
            {record.owner_email && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {record.owner_email}
              </Text>
            )}
          </Space>
        )
      },
    },
    {
      title: '总运行次数',
      dataIndex: 'total_runs',
      key: 'total_runs',
      width: 100,
      sorter: (a: JobStats, b: JobStats) => a.total_runs - b.total_runs,
      render: (totalRuns: number) => <Text strong>{totalRuns}</Text>,
    },
    {
      title: '成功/失败',
      key: 'success_failure',
      width: 140,
      render: (_: any, record: JobStats) => (
        <Space size="small">
          <Tag color="success" icon={<CheckCircleOutlined />}>
            {record.success_runs}
          </Tag>
          <Tag color="error" icon={<CloseCircleOutlined />}>
            {record.failure_runs}
          </Tag>
        </Space>
      ),
    },
    {
      title: '成功率',
      dataIndex: 'success_rate',
      key: 'success_rate',
      width: 100,
      sorter: (a: JobStats, b: JobStats) => a.success_rate - b.success_rate,
      render: (successRate: number) => {
        const color = successRate >= 90 ? '#52c41a' :
                      successRate >= 70 ? '#1890ff' : '#ff4d4f'
        return (
          <Text strong style={{ color }}>
            {successRate.toFixed(1)}%
          </Text>
        )
      },
    },
    {
      title: '平均时长',
      dataIndex: 'avg_duration_seconds',
      key: 'avg_duration_seconds',
      width: 100,
      sorter: (a: JobStats, b: JobStats) =>
        (a.avg_duration_seconds || 0) - (b.avg_duration_seconds || 0),
      render: (avgDuration: number | null) => formatDuration(avgDuration),
    },
    {
      title: '最小/最大时长',
      key: 'duration_range',
      width: 130,
      render: (_: any, record: JobStats) => (
        <Space size="small">
          <Text type="secondary" style={{ fontSize: 12 }}>
            {formatDuration(record.min_duration_seconds)} / {formatDuration(record.max_duration_seconds)}
          </Text>
        </Space>
      ),
    },
    {
      title: '最近运行',
      dataIndex: 'last_run_at',
      key: 'last_run_at',
      width: 160,
      render: (lastRunAt: string | null) => {
        if (!lastRunAt) return '-'
        return (
          <Space direction="vertical" size={0}>
            <Text>{formatTimezone(lastRunAt, 'YYYY-MM-DD')}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {formatTimezone(lastRunAt, 'HH:mm:ss')}
            </Text>
          </Space>
        )
      },
    },
    {
      title: '最近状态',
      key: 'last_status',
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
      onFilter: (value: any, record: JobStats) => {
        if (!record.last_conclusion) return value === 'other'
        if (value === 'other') {
          return record.last_conclusion !== 'success' && record.last_conclusion !== 'failure' && record.last_conclusion !== 'cancelled'
        }
        return record.last_conclusion === value
      },
      render: (_: any, record: JobStats) => {
        if (!record.last_conclusion) return '-'
        return renderConclusionTag(record.last_conclusion)
      },
    },
    {
      title: '问题分类',
      key: 'problem_category',
      width: 100,
      render: (_: any, record: JobStats) => {
        const key = `${record.workflow_name}-${record.job_name}`
        const category = categoryMap.get(key)
        if (!category) return '-'
        const catInfo = PROBLEM_CATEGORY_MAP[category] || { color: '#64748d', label: category }
        return <Tag color={catInfo.color}>{catInfo.label}</Tag>
      },
    },
  ]

  return (
    <div>
      {/* 页面标题和操作区 */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            Job 运行统计
          </Title>
          <Text type="secondary">
            展示各 Job 的运行情况和成功率统计
          </Text>
        </div>
        <Space>
          <Select
            value={daysFilter}
            onChange={setDaysFilter}
            options={[
              { label: '最近 7 天', value: 7 },
              { label: '最近 14 天', value: 14 },
              { label: '最近 30 天', value: 30 },
              { label: '全部数据', value: 'all' },
            ]}
            style={{ width: 120 }}
          />
          <Button
            icon={<ReloadOutlined />}
            onClick={() => refetch()}
          >
            刷新
          </Button>
        </Space>
      </div>

      {/* 统计表格 */}
      <Card>
        <Table
          columns={columns}
          dataSource={filteredJobStats}
          loading={isLoading}
          rowKey={(record) => `${record.workflow_name}-${record.job_name}`}
          pagination={{
            pageSize: 20,
            showSizeChanger: false,
            showTotal: (total) => `共 ${total} 条记录`,
          }}
          scroll={{ x: 1400 }}
          size="middle"
          onChange={(_, filters) => {
            if (filters.workflow_name) {
              setWorkflowFilter(filters.workflow_name as string[])
            } else {
              setWorkflowFilter([])
            }
            if (filters.owner) {
              setOwnerFilter(filters.owner as string[])
            } else {
              setOwnerFilter([])
            }
            if (filters.last_status) {
              setConclusionFilter(filters.last_status as string[])
            } else {
              setConclusionFilter([])
            }
          }}
          onRow={(record: JobStats) => ({
            onClick: () => navigate(`/ci/jobs/${encodeURIComponent(record.workflow_name)}/${encodeURIComponent(record.job_name)}`),
            style: { cursor: 'pointer' },
          })}
        />
      </Card>
    </div>
  )
}

export default JobBoard
