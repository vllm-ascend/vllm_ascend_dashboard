import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Tabs, Statistic, Row, Col, Table, Tag, Space, Button, message, Spin, Typography, Progress, Avatar, Tooltip, Badge, Select, Input, DatePicker } from 'antd'
import { PullRequestOutlined, SyncOutlined, DashboardOutlined, AppstoreOutlined, UnorderedListOutlined, BarChartOutlined, TeamOutlined, ClockCircleOutlined, CheckCircleOutlined, ExclamationCircleOutlined, ThunderboltOutlined } from '@ant-design/icons'
import * as hooks from '../hooks/usePRPipeline'
import type { PullRequestResponse, PRPipelineOverview, PRPipelineKanban, PRPipelineMetrics, PRPipelineContributor, PRPipelineListResponse, PRPipelineTrendsResponse } from '../services/prPipeline'
import dayjs from 'dayjs'

const { Text, Title } = Typography

const PIPELINE_STAGE_COLORS: Record<string, string> = {
  submitted: 'default',
  reviewing: 'processing',
  approved: 'success',
  ci_running: 'warning',
  ci_passed: 'lime',
  ci_failed: 'error',
  merging: 'purple',
  merged: 'cyan',
  closed: 'default',
}

const STATE_COLORS: Record<string, string> = {
  open: 'blue',
  merged: 'green',
  closed: 'red',
}

const REVIEW_STATUS_COLORS: Record<string, string> = {
  none: 'default',
  reviewing: 'processing',
  approved: 'success',
  changes_requested: 'warning',
}

const CI_STATUS_COLORS: Record<string, string> = {
  success: 'success',
  failure: 'error',
  in_progress: 'processing',
  queued: 'default',
  cancelled: 'warning',
}

const STAGE_LABELS: Record<string, string> = {
  submitted: '已提交',
  reviewing: '评审中',
  approved: '已通过',
  ci_running: 'CI 运行中',
  ci_passed: 'CI 通过',
  ci_failed: 'CI 失败',
  merging: '合并中',
  merged: '已合并',
  closed: '已关闭',
}

const PERIOD_OPTIONS = [
  { value: 7, label: '7 天' },
  { value: 30, label: '30 天' },
  { value: 90, label: '90 天' },
  { value: 365, label: '365 天' },
]

const STAGE_COLUMNS = ['submitted', 'reviewing', 'approved', 'ci_running', 'ci_passed', 'ci_failed', 'merging', 'merged', 'closed'] as const

const renderPipelineStageTag = (stage: string | null) => {
  if (!stage) return <Tag>—</Tag>
  return <Tag color={PIPELINE_STAGE_COLORS[stage] || 'default'}>{STAGE_LABELS[stage] || stage}</Tag>
}

const STATE_LABELS: Record<string, string> = {
  open: '开启',
  merged: '已合并',
  closed: '已关闭',
}

const REVIEW_STATUS_LABELS: Record<string, string> = {
  none: '无',
  reviewing: '评审中',
  approved: '已通过',
  changes_requested: '要求修改',
}

const CI_STATUS_LABELS: Record<string, string> = {
  success: '通过',
  failure: '失败',
  in_progress: '运行中',
  queued: '排队中',
  cancelled: '已取消',
}

const renderStateTag = (state: string) => <Tag color={STATE_COLORS[state] || 'default'}>{STATE_LABELS[state] || state}</Tag>

const renderReviewStatusTag = (status: string | null) => {
  if (!status) return <Tag>无</Tag>
  return <Tag color={REVIEW_STATUS_COLORS[status] || 'default'}>{REVIEW_STATUS_LABELS[status] || status}</Tag>
}

const renderCIStatusTag = (status: string | null) => {
  if (!status) return <Tag>—</Tag>
  return <Tag color={CI_STATUS_COLORS[status] || 'default'}>{CI_STATUS_LABELS[status] || status}</Tag>
}

const renderAvatar = (author: string, avatarUrl: string | null) => (
  <Space size={4}>
    <Avatar size={20} src={avatarUrl} style={{ backgroundColor: '#1677ff' }}>
      {author?.[0]?.toUpperCase()}
    </Avatar>
    <Text>{author}</Text>
  </Space>
)

const formatHours = (hours: number | null) => {
  if (hours === null || hours === undefined) return '—'
  if (hours < 1) return `${Math.round(hours * 60)}m`
  if (hours < 24) return `${Math.round(hours)}h`
  return `${(hours / 24).toFixed(1)}d`
}

const getBacklogColor = (index: number) => {
  if (index < 15) return '#52c41a'
  if (index <= 25) return '#faad14'
  return '#ff4d4f'
}

const OverviewTab = ({ period }: { period: number }) => {
  const { data, isLoading } = hooks.usePRPipelineOverview(period)

  if (isLoading) return <Spin style={{ display: 'block', margin: '40px auto' }} />
  if (!data) return <Text type="secondary">暂无数据</Text>

  const backlogColor = getBacklogColor(data.backlog_index)

  return (
    <div>
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic title="开启" value={data.open_count} prefix={<PullRequestOutlined />} valueStyle={{ color: '#1677ff' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="已合并" value={data.merged_count} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="已关闭" value={data.closed_count} prefix={<ExclamationCircleOutlined />} valueStyle={{ color: '#ff4d4f' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="草稿" value={data.draft_count} prefix={<ClockCircleOutlined />} valueStyle={{ color: '#faad14' }} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="积压指数"
              value={data.backlog_index}
              suffix="个PR"
              valueStyle={{ color: backlogColor }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="合并率"
              value={data.merge_rate}
              suffix="%"
              precision={1}
              valueStyle={{ color: data.merge_rate >= 60 ? '#52c41a' : '#faad14' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="平均首次 Review"
              value={formatHours(data.avg_time_to_first_review_hours)}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="平均合并时间"
              value={formatHours(data.avg_time_to_merge_hours)}
              prefix={<ThunderboltOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Card title="流水线阶段分布" style={{ marginBottom: 24 }}>
        <Space size={[8, 12]} wrap>
          {Object.entries(data.pipeline_stage_distribution || {}).map(([stage, count]: [string, number]) => (
            <Tag key={stage} color={PIPELINE_STAGE_COLORS[stage] || 'default'} style={{ fontSize: 14, padding: '4px 12px' }}>
              {STAGE_LABELS[stage] || stage}: {count}
            </Tag>
          ))}
        </Space>
      </Card>

      {data.last_sync_at && (
        <Text type="secondary" style={{ marginTop: 16, display: 'block' }}>
          最后同步: {dayjs(data.last_sync_at).format('YYYY-MM-DD HH:mm:ss')}
        </Text>
      )}
    </div>
  )
}

const KanbanTab = () => {
  const navigate = useNavigate()
  const [kanbanState, setKanbanState] = useState<string>('open')
  const [includeDraft, setIncludeDraft] = useState<boolean>(false)
  const { data, isLoading } = hooks.usePRPipelineKanban(kanbanState, includeDraft, 20)

  if (isLoading) return <Spin style={{ display: 'block', margin: '40px auto' }} />

  const handleCardClick = (prNumber: number) => {
    navigate(`/pr-pipeline/${prNumber}`)
  }

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center' }}>
        <Select
          value={kanbanState}
          onChange={setKanbanState}
          style={{ width: 120 }}
          options={[
            { value: 'open', label: '开启' },
            { value: 'all', label: '全部' },
          ]}
        />
        <Space>
          <Text>包含草稿：</Text>
          <Select
            value={includeDraft ? 'yes' : 'no'}
            onChange={(v) => setIncludeDraft(v === 'yes')}
            style={{ width: 80 }}
            options={[
              { value: 'no', label: '否' },
              { value: 'yes', label: '是' },
            ]}
          />
        </Space>
      </div>

      {!data ? (
        <Text type="secondary">暂无数据</Text>
      ) : (
        <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 16 }}>
          {STAGE_COLUMNS.map((stage) => {
            const prs = data[stage] || []
            if (prs.length === 0 && kanbanState === 'open' && stage !== 'submitted') return null
            return (
              <div
                key={stage}
                style={{
                  minWidth: 280,
                  maxWidth: 320,
                  flex: '0 0 300px',
                  display: 'flex',
                  flexDirection: 'column',
                }}
              >
                <div
                  style={{
                    padding: '8px 12px',
                    borderRadius: '6px 6px 0 0',
                    fontWeight: 600,
                    fontSize: 14,
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    backgroundColor: stage === 'submitted' ? '#f0f0f0' :
                      stage === 'reviewing' ? '#e6f7ff' :
                      stage === 'approved' ? '#f6ffed' :
                      stage === 'ci_running' ? '#fff7e6' :
                      stage === 'ci_passed' ? '#f6ffed' :
                      stage === 'ci_failed' ? '#fff2f0' :
                      stage === 'merging' ? '#f9f0ff' :
                      stage === 'merged' ? '#e6fffb' :
                      '#fafafa',
                  }}
                >
                  <Tag color={PIPELINE_STAGE_COLORS[stage]} style={{ fontSize: 13 }}>
                    {STAGE_LABELS[stage]}
                  </Tag>
                  <Badge count={prs.length} style={{ backgroundColor: '#666' }} />
                </div>
                <div
                  style={{
                    flex: 1,
                    padding: '8px',
                    backgroundColor: '#fafafa',
                    borderRadius: '0 0 6px 6px',
                    overflowY: 'auto',
                    maxHeight: 600,
                  }}
                >
                  {prs.length === 0 && (
                      <Text type="secondary" style={{ display: 'block', textAlign: 'center', padding: 16 }}>
                        暂无 PR
                      </Text>
                  )}
                  {prs.map((pr: PullRequestResponse) => (
                    <Card
                      key={pr.id}
                      size="small"
                      hoverable
                      style={{ marginBottom: 8, cursor: 'pointer' }}
                      onClick={() => handleCardClick(pr.pr_number)}
                    >
                      <div style={{ marginBottom: 4 }}>
                        <Text strong ellipsis style={{ maxWidth: 240, display: 'inline-block' }}>
                          {pr.title}
                        </Text>
                      </div>
                      <div style={{ marginBottom: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
                        <Avatar size={16} src={pr.author_avatar_url}>
                          {pr.author?.[0]?.toUpperCase()}
                        </Avatar>
                        <Text style={{ fontSize: 12 }}>#{pr.pr_number}</Text>
                        <Text style={{ fontSize: 12, color: '#999' }}>{pr.author}</Text>
                      </div>
                      <div style={{ marginBottom: 4 }}>
                        <Space size={4}>
                          {pr.is_draft && <Tag color="gold" style={{ fontSize: 11 }}>草稿</Tag>}
                          {pr.review_status && <Tag color={REVIEW_STATUS_COLORS[pr.review_status] || 'default'} style={{ fontSize: 11 }}>{pr.review_status}</Tag>}
                          {pr.ci_status && <Tag color={CI_STATUS_COLORS[pr.ci_status] || 'default'} style={{ fontSize: 11 }}>{pr.ci_status}</Tag>}
                          {pr.labels?.slice(0, 2).map((label: string) => (
                            <Tag key={label} style={{ fontSize: 11 }}>{label}</Tag>
                          ))}
                        </Space>
                      </div>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {dayjs(pr.created_at).fromNow()}
                      </Text>
                    </Card>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

const ListTab = () => {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [stateFilter, setStateFilter] = useState<string | undefined>(undefined)
  const [authorFilter, setAuthorFilter] = useState<string | undefined>(undefined)
  const [stageFilter, setStageFilter] = useState<string | undefined>(undefined)
  const [searchFilter, setSearchFilter] = useState<string | undefined>(undefined)

  const { data, isLoading } = hooks.usePRPipelineList({
    state: stateFilter,
    author: authorFilter,
    pipeline_stage: stageFilter,
    search: searchFilter,
    page,
    page_size: pageSize,
  })

  const columns = [
    {
      title: 'PR #',
      dataIndex: 'pr_number',
      key: 'pr_number',
      width: 80,
      render: (prNumber: number) => (
        <a onClick={() => navigate(`/pr-pipeline/${prNumber}`)} style={{ fontWeight: 500 }}>
          #{prNumber}
        </a>
      ),
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      width: 250,
      ellipsis: true,
    },
    {
      title: '作者',
      dataIndex: 'author',
      key: 'author',
      width: 150,
      render: (author: string, record: PullRequestResponse) => renderAvatar(author, record.author_avatar_url),
    },
    {
      title: '状态',
      dataIndex: 'state',
      key: 'state',
      width: 80,
      render: (state: string) => renderStateTag(state),
    },
    {
      title: '流水线阶段',
      dataIndex: 'pipeline_stage',
      key: 'pipeline_stage',
      width: 120,
      render: (stage: string | null) => renderPipelineStageTag(stage),
    },
    {
      title: 'Review 状态',
      dataIndex: 'review_status',
      key: 'review_status',
      width: 120,
      render: (status: string | null) => renderReviewStatusTag(status),
    },
    {
      title: 'CI 状态',
      dataIndex: 'ci_status',
      key: 'ci_status',
      width: 100,
      render: (status: string | null) => renderCIStatusTag(status),
    },
    {
      title: '草稿',
      dataIndex: 'is_draft',
      key: 'is_draft',
      width: 60,
      render: (draft: boolean) => draft ? <Badge status="warning" text="草稿" /> : <Badge status="default" text="—" />,
    },
    {
      title: '首次 Review',
      dataIndex: 'time_to_first_review_hours',
      key: 'time_to_first_review_hours',
      width: 100,
      render: (hours: number | null) => formatHours(hours),
    },
    {
      title: '合并耗时',
      dataIndex: 'time_to_merge_hours',
      key: 'time_to_merge_hours',
      width: 100,
      render: (hours: number | null) => formatHours(hours),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 140,
      render: (date: string) => dayjs(date).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 140,
      render: (date: string | null) => date ? dayjs(date).format('YYYY-MM-DD HH:mm') : '—',
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <Select
          placeholder="状态"
          allowClear
          style={{ width: 120 }}
          value={stateFilter}
          onChange={setStateFilter}
          options={[
            { value: 'open', label: '开启' },
            { value: 'merged', label: '已合并' },
            { value: 'closed', label: '已关闭' },
          ]}
        />
        <Input
          placeholder="作者"
          allowClear
          style={{ width: 150 }}
          value={authorFilter}
          onChange={(e) => setAuthorFilter(e.target.value || undefined)}
        />
        <Select
          placeholder="流水线阶段"
          allowClear
          style={{ width: 150 }}
          value={stageFilter}
          onChange={setStageFilter}
          options={STAGE_COLUMNS.map((s) => ({ value: s, label: STAGE_LABELS[s] }))}
        />
        <Input.Search
          placeholder="搜索 PR"
          allowClear
          style={{ width: 200 }}
          value={searchFilter}
          onChange={(e) => setSearchFilter(e.target.value || undefined)}
          onSearch={(v) => setSearchFilter(v || undefined)}
        />
      </div>

      <Table
        columns={columns}
        dataSource={data?.items || []}
        loading={isLoading}
        rowKey="id"
        pagination={{
          current: page,
          pageSize,
          total: data?.total || 0,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 个 PR`,
          onChange: (p, ps) => {
            setPage(p)
            setPageSize(ps)
          },
        }}
        scroll={{ x: 1400 }}
        onRow={(record: PullRequestResponse) => ({
          onClick: () => navigate(`/pr-pipeline/${record.pr_number}`),
          style: { cursor: 'pointer' },
        })}
      />
    </div>
  )
}

const MetricsTab = ({ period }: { period: number }) => {
  const { data, isLoading } = hooks.usePRPipelineMetrics(period)

  if (isLoading) return <Spin style={{ display: 'block', margin: '40px auto' }} />
  if (!data) return <Text type="secondary">暂无数据</Text>

  const backlogColor = getBacklogColor(data.backlog_index)

  const metricRows = [
    { label: '首次响应', key: 'first_response_hours', metric: data.first_response_hours },
    { label: 'Review → 通过', key: 'review_to_approval_hours', metric: data.review_to_approval_hours },
    { label: 'CI 耗时', key: 'ci_duration_hours', metric: data.ci_duration_hours },
    { label: '合并时间', key: 'merge_hours', metric: data.merge_hours },
    { label: '总周期', key: 'total_cycle_hours', metric: data.total_cycle_hours },
  ]

  return (
    <div>
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card>
            <Statistic
              title="合并率"
              value={data.merge_rate}
              suffix="%"
              precision={1}
              valueStyle={{ color: data.merge_rate >= 60 ? '#52c41a' : '#faad14' }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="积压指数"
              value={data.backlog_index}
              suffix="个PR"
              valueStyle={{ color: backlogColor }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="已分析 PR 数" value={data.total_cycle_hours?.count || 0} />
          </Card>
        </Col>
      </Row>

      <Card title="百分位指标（小时）" style={{ marginBottom: 24 }}>
        <Table
          dataSource={metricRows}
          rowKey="key"
          pagination={false}
          columns={[
            {
              title: '指标',
              dataIndex: 'label',
              key: 'label',
              width: 200,
            },
            {
              title: 'P50',
              key: 'p50',
              width: 120,
              render: (_, row) => formatHours(row.metric?.p50),
            },
            {
              title: 'P90',
              key: 'p90',
              width: 120,
              render: (_, row) => formatHours(row.metric?.p90),
            },
            {
              title: '平均值',
              key: 'avg',
              width: 120,
              render: (_, row) => formatHours(row.metric?.avg),
            },
            {
              title: '数量',
              key: 'count',
              width: 80,
              render: (_, row) => row.metric?.count || 0,
            },
          ]}
        />
      </Card>

      {data.survival_distribution && data.survival_distribution.length > 0 && (
        <Card title="存活分布">
          <Space direction="vertical" size={8}>
            {data.survival_distribution.map((point: { day: number; hours_threshold: number; cumulative_percent: number; count: number }) => (
              <div key={point.day} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Text strong>{Math.round(point.cumulative_percent)}%</Text>
                <Text type="secondary">的 PR 在</Text>
                <Text>{point.day} 天内</Text>
                <Text type="secondary">合并 ({Math.round(point.hours_threshold)}h)</Text>
                <Progress
                  percent={Math.round(point.cumulative_percent)}
                  size="small"
                  style={{ width: 200 }}
                  strokeColor={point.cumulative_percent >= 80 ? '#52c41a' : '#1677ff'}
                />
              </div>
            ))}
          </Space>
        </Card>
      )}
    </div>
  )
}

const ContributorsTab = ({ period }: { period: number }) => {
  const [contributorType, setContributorType] = useState<string | undefined>(undefined)
  const { data, isLoading } = hooks.usePRPipelineContributors(period, contributorType, 20)

  if (isLoading) return <Spin style={{ display: 'block', margin: '40px auto' }} />

  const authors = (data || []).filter((c: PRPipelineContributor) => c.type === 'author' || c.pr_count > 0)
  const reviewers = (data || []).filter((c: PRPipelineContributor) => c.type === 'reviewer' || c.review_count > 0)

  const authorColumns = [
    {
      title: '作者',
      key: 'username',
      width: 180,
      render: (_: unknown, record: PRPipelineContributor) => renderAvatar(record.username, record.avatar_url),
    },
    {
      title: 'PR 数量',
      dataIndex: 'pr_count',
      key: 'pr_count',
      width: 100,
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => a.pr_count - b.pr_count,
    },
    {
      title: '已合并',
      dataIndex: 'merged_count',
      key: 'merged_count',
      width: 100,
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => a.merged_count - b.merged_count,
    },
    {
      title: '新增行数',
      dataIndex: 'lines_added',
      key: 'lines_added',
      width: 120,
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => a.lines_added - b.lines_added,
    },
    {
      title: '删除行数',
      dataIndex: 'lines_removed',
      key: 'lines_removed',
      width: 120,
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => a.lines_removed - b.lines_removed,
    },
  ]

  const reviewerColumns = [
    {
      title: '评审人',
      key: 'username',
      width: 180,
      render: (_: unknown, record: PRPipelineContributor) => renderAvatar(record.username, record.avatar_url),
    },
    {
      title: 'Review 数量',
      dataIndex: 'review_count',
      key: 'review_count',
      width: 120,
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => a.review_count - b.review_count,
    },
    {
      title: '平均首次响应',
      dataIndex: 'avg_first_response_hours',
      key: 'avg_first_response_hours',
      width: 150,
      render: (hours: number | null) => formatHours(hours),
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => (a.avg_first_response_hours || 0) - (b.avg_first_response_hours || 0),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center' }}>
        <Select
          placeholder="贡献者类型"
          allowClear
          style={{ width: 150 }}
          value={contributorType}
          onChange={setContributorType}
          options={[
            { value: 'author', label: '作者' },
            { value: 'reviewer', label: '评审人' },
          ]}
        />
      </div>

      {!contributorType || contributorType === 'author' ? (
        <Card title="Top 作者" style={{ marginBottom: 24 }}>
          <Table
            columns={authorColumns}
            dataSource={authors}
            loading={isLoading}
            rowKey="username"
            pagination={{ pageSize: 10 }}
          />
        </Card>
      ) : null}

      {!contributorType || contributorType === 'reviewer' ? (
        <Card title="Top 评审人">
          <Table
            columns={reviewerColumns}
            dataSource={reviewers}
            loading={isLoading}
            rowKey="username"
            pagination={{ pageSize: 10 }}
          />
        </Card>
      ) : null}
    </div>
  )
}

const PRPipelineBoard = () => {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('overview')
  const [overviewPeriod, setOverviewPeriod] = useState(30)
  const [metricsPeriod, setMetricsPeriod] = useState(30)
  const [contributorsPeriod, setContributorsPeriod] = useState(30)
  const syncMutation = hooks.usePRPipelineSync()

  const handleSync = () => {
    syncMutation.mutate(undefined, {
      onSuccess: (data) => {
        message.success(data?.message || '同步完成')
      },
      onError: (error: any) => {
        message.error(error?.response?.data?.detail || '同步失败')
      },
    })
  }

  const tabItems = [
    {
      key: 'overview',
      label: (
          <Space>
            <DashboardOutlined />
            <span>概览</span>
          </Space>
      ),
      children: (
        <div>
          <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'flex-end' }}>
            <Select
              value={overviewPeriod}
              onChange={setOverviewPeriod}
              options={PERIOD_OPTIONS}
              style={{ width: 120 }}
            />
          </div>
          <OverviewTab period={overviewPeriod} />
        </div>
      ),
    },
    {
      key: 'kanban',
      label: (
          <Space>
            <AppstoreOutlined />
            <span>看板</span>
          </Space>
      ),
      children: <KanbanTab />,
    },
    {
      key: 'list',
      label: (
          <Space>
            <UnorderedListOutlined />
            <span>列表</span>
          </Space>
      ),
      children: <ListTab />,
    },
    {
      key: 'metrics',
      label: (
          <Space>
            <BarChartOutlined />
            <span>指标</span>
          </Space>
      ),
      children: (
        <div>
          <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'flex-end' }}>
            <Select
              value={metricsPeriod}
              onChange={setMetricsPeriod}
              options={PERIOD_OPTIONS}
              style={{ width: 120 }}
            />
          </div>
          <MetricsTab period={metricsPeriod} />
        </div>
      ),
    },
    {
      key: 'contributors',
      label: (
          <Space>
            <TeamOutlined />
            <span>贡献者</span>
          </Space>
      ),
      children: (
        <div>
          <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'flex-end' }}>
            <Select
              value={contributorsPeriod}
              onChange={setContributorsPeriod}
              options={PERIOD_OPTIONS}
              style={{ width: 120 }}
            />
          </div>
          <ContributorsTab period={contributorsPeriod} />
        </div>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>PR 流水线看板</Title>
          <Text type="secondary">跟踪 Pull Requests 的 Review 和 CI 流水线</Text>
        </div>
        <Button
          icon={<SyncOutlined />}
          loading={syncMutation.isPending}
          onClick={handleSync}
        >
          同步数据
        </Button>
      </div>

      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
    </div>
  )
}

export default PRPipelineBoard
