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
  submitted: 'Submitted',
  reviewing: 'Reviewing',
  approved: 'Approved',
  ci_running: 'CI Running',
  ci_passed: 'CI Passed',
  ci_failed: 'CI Failed',
  merging: 'Merging',
  merged: 'Merged',
  closed: 'Closed',
}

const PERIOD_OPTIONS = [
  { value: 7, label: '7 days' },
  { value: 30, label: '30 days' },
  { value: 90, label: '90 days' },
  { value: 365, label: '365 days' },
]

const STAGE_COLUMNS = ['submitted', 'reviewing', 'approved', 'ci_running', 'ci_passed', 'ci_failed', 'merging', 'merged', 'closed'] as const

const renderPipelineStageTag = (stage: string | null) => {
  if (!stage) return <Tag>—</Tag>
  return <Tag color={PIPELINE_STAGE_COLORS[stage] || 'default'}>{STAGE_LABELS[stage] || stage}</Tag>
}

const renderStateTag = (state: string) => <Tag color={STATE_COLORS[state] || 'default'}>{state}</Tag>

const renderReviewStatusTag = (status: string | null) => {
  if (!status) return <Tag>none</Tag>
  return <Tag color={REVIEW_STATUS_COLORS[status] || 'default'}>{status}</Tag>
}

const renderCIStatusTag = (status: string | null) => {
  if (!status) return <Tag>—</Tag>
  return <Tag color={CI_STATUS_COLORS[status] || 'default'}>{status}</Tag>
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
  if (!data) return <Text type="secondary">No data available</Text>

  const backlogColor = getBacklogColor(data.backlog_index)

  return (
    <div>
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic title="Open" value={data.open_count} prefix={<PullRequestOutlined />} valueStyle={{ color: '#1677ff' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="Merged" value={data.merged_count} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="Closed" value={data.closed_count} prefix={<ExclamationCircleOutlined />} valueStyle={{ color: '#ff4d4f' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="Draft" value={data.draft_count} prefix={<ClockCircleOutlined />} valueStyle={{ color: '#faad14' }} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="Backlog Index"
              value={data.backlog_index}
              suffix="PRs"
              valueStyle={{ color: backlogColor }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="Merge Rate"
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
              title="Avg First Review"
              value={formatHours(data.avg_time_to_first_review_hours)}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="Avg Time to Merge"
              value={formatHours(data.avg_time_to_merge_hours)}
              prefix={<ThunderboltOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Card title="Pipeline Stage Distribution" style={{ marginBottom: 24 }}>
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
          Last synced: {dayjs(data.last_sync_at).format('YYYY-MM-DD HH:mm:ss')}
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
            { value: 'open', label: 'Open' },
            { value: 'all', label: 'All' },
          ]}
        />
        <Space>
          <Text>Include Draft:</Text>
          <Select
            value={includeDraft ? 'yes' : 'no'}
            onChange={(v) => setIncludeDraft(v === 'yes')}
            style={{ width: 80 }}
            options={[
              { value: 'no', label: 'No' },
              { value: 'yes', label: 'Yes' },
            ]}
          />
        </Space>
      </div>

      {!data ? (
        <Text type="secondary">No data available</Text>
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
                      No PRs
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
                          {pr.is_draft && <Tag color="gold" style={{ fontSize: 11 }}>Draft</Tag>}
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
      title: 'Title',
      dataIndex: 'title',
      key: 'title',
      width: 250,
      ellipsis: true,
    },
    {
      title: 'Author',
      dataIndex: 'author',
      key: 'author',
      width: 150,
      render: (author: string, record: PullRequestResponse) => renderAvatar(author, record.author_avatar_url),
    },
    {
      title: 'State',
      dataIndex: 'state',
      key: 'state',
      width: 80,
      render: (state: string) => renderStateTag(state),
    },
    {
      title: 'Pipeline Stage',
      dataIndex: 'pipeline_stage',
      key: 'pipeline_stage',
      width: 120,
      render: (stage: string | null) => renderPipelineStageTag(stage),
    },
    {
      title: 'Review Status',
      dataIndex: 'review_status',
      key: 'review_status',
      width: 120,
      render: (status: string | null) => renderReviewStatusTag(status),
    },
    {
      title: 'CI Status',
      dataIndex: 'ci_status',
      key: 'ci_status',
      width: 100,
      render: (status: string | null) => renderCIStatusTag(status),
    },
    {
      title: 'Draft',
      dataIndex: 'is_draft',
      key: 'is_draft',
      width: 60,
      render: (draft: boolean) => draft ? <Badge status="warning" text="Draft" /> : <Badge status="default" text="—" />,
    },
    {
      title: 'First Review',
      dataIndex: 'time_to_first_review_hours',
      key: 'time_to_first_review_hours',
      width: 100,
      render: (hours: number | null) => formatHours(hours),
    },
    {
      title: 'Time to Merge',
      dataIndex: 'time_to_merge_hours',
      key: 'time_to_merge_hours',
      width: 100,
      render: (hours: number | null) => formatHours(hours),
    },
    {
      title: 'Created',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 140,
      render: (date: string) => dayjs(date).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: 'Updated',
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
          placeholder="State"
          allowClear
          style={{ width: 120 }}
          value={stateFilter}
          onChange={setStateFilter}
          options={[
            { value: 'open', label: 'Open' },
            { value: 'merged', label: 'Merged' },
            { value: 'closed', label: 'Closed' },
          ]}
        />
        <Input
          placeholder="Author"
          allowClear
          style={{ width: 150 }}
          value={authorFilter}
          onChange={(e) => setAuthorFilter(e.target.value || undefined)}
        />
        <Select
          placeholder="Pipeline Stage"
          allowClear
          style={{ width: 150 }}
          value={stageFilter}
          onChange={setStageFilter}
          options={STAGE_COLUMNS.map((s) => ({ value: s, label: STAGE_LABELS[s] }))}
        />
        <Input.Search
          placeholder="Search PRs"
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
          showTotal: (total) => `Total ${total} PRs`,
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
  if (!data) return <Text type="secondary">No data available</Text>

  const backlogColor = getBacklogColor(data.backlog_index)

  const metricRows = [
    { label: 'First Response', key: 'first_response_hours', metric: data.first_response_hours },
    { label: 'Review → Approval', key: 'review_to_approval_hours', metric: data.review_to_approval_hours },
    { label: 'CI Duration', key: 'ci_duration_hours', metric: data.ci_duration_hours },
    { label: 'Merge Time', key: 'merge_hours', metric: data.merge_hours },
    { label: 'Total Cycle', key: 'total_cycle_hours', metric: data.total_cycle_hours },
  ]

  return (
    <div>
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card>
            <Statistic
              title="Merge Rate"
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
              title="Backlog Index"
              value={data.backlog_index}
              suffix="PRs"
              valueStyle={{ color: backlogColor }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="PRs Analyzed" value={data.total_cycle_hours?.count || 0} />
          </Card>
        </Col>
      </Row>

      <Card title="Percentile Metrics (hours)" style={{ marginBottom: 24 }}>
        <Table
          dataSource={metricRows}
          rowKey="key"
          pagination={false}
          columns={[
            {
              title: 'Metric',
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
              title: 'Average',
              key: 'avg',
              width: 120,
              render: (_, row) => formatHours(row.metric?.avg),
            },
            {
              title: 'Count',
              key: 'count',
              width: 80,
              render: (_, row) => row.metric?.count || 0,
            },
          ]}
        />
      </Card>

      {data.survival_distribution && data.survival_distribution.length > 0 && (
        <Card title="Survival Distribution">
          <Space direction="vertical" size={8}>
            {data.survival_distribution.map((point: { day: number; hours_threshold: number; cumulative_percent: number; count: number }) => (
              <div key={point.day} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Text strong>{Math.round(point.cumulative_percent)}%</Text>
                <Text type="secondary">of PRs merged within</Text>
                <Text>{point.day} day(s)</Text>
                <Text type="secondary">({Math.round(point.hours_threshold)}h)</Text>
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
      title: 'Author',
      key: 'username',
      width: 180,
      render: (_: unknown, record: PRPipelineContributor) => renderAvatar(record.username, record.avatar_url),
    },
    {
      title: 'PR Count',
      dataIndex: 'pr_count',
      key: 'pr_count',
      width: 100,
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => a.pr_count - b.pr_count,
    },
    {
      title: 'Merged',
      dataIndex: 'merged_count',
      key: 'merged_count',
      width: 100,
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => a.merged_count - b.merged_count,
    },
    {
      title: 'Lines Added',
      dataIndex: 'lines_added',
      key: 'lines_added',
      width: 120,
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => a.lines_added - b.lines_added,
    },
    {
      title: 'Lines Removed',
      dataIndex: 'lines_removed',
      key: 'lines_removed',
      width: 120,
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => a.lines_removed - b.lines_removed,
    },
  ]

  const reviewerColumns = [
    {
      title: 'Reviewer',
      key: 'username',
      width: 180,
      render: (_: unknown, record: PRPipelineContributor) => renderAvatar(record.username, record.avatar_url),
    },
    {
      title: 'Review Count',
      dataIndex: 'review_count',
      key: 'review_count',
      width: 120,
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => a.review_count - b.review_count,
    },
    {
      title: 'Avg First Response',
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
          placeholder="Contributor Type"
          allowClear
          style={{ width: 150 }}
          value={contributorType}
          onChange={setContributorType}
          options={[
            { value: 'author', label: 'Authors' },
            { value: 'reviewer', label: 'Reviewers' },
          ]}
        />
      </div>

      {!contributorType || contributorType === 'author' ? (
        <Card title="Top Authors" style={{ marginBottom: 24 }}>
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
        <Card title="Top Reviewers">
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
        message.success(data?.message || 'Sync completed')
      },
      onError: (error: any) => {
        message.error(error?.response?.data?.detail || 'Sync failed')
      },
    })
  }

  const tabItems = [
    {
      key: 'overview',
      label: (
        <Space>
          <DashboardOutlined />
          <span>Overview</span>
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
          <span>Kanban</span>
        </Space>
      ),
      children: <KanbanTab />,
    },
    {
      key: 'list',
      label: (
        <Space>
          <UnorderedListOutlined />
          <span>List</span>
        </Space>
      ),
      children: <ListTab />,
    },
    {
      key: 'metrics',
      label: (
        <Space>
          <BarChartOutlined />
          <span>Metrics</span>
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
          <span>Contributors</span>
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
          <Title level={3} style={{ margin: 0 }}>PR Pipeline Board</Title>
          <Text type="secondary">Track pull requests through the review and CI pipeline</Text>
        </div>
        <Button
          icon={<SyncOutlined />}
          loading={syncMutation.isPending}
          onClick={handleSync}
        >
          Sync Data
        </Button>
      </div>

      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
    </div>
  )
}

export default PRPipelineBoard
