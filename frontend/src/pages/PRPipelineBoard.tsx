import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Tabs, Statistic, Row, Col, Table, Tag, Space, Button, message, Spin, Typography, Avatar, Tooltip, Badge, Select, Input } from 'antd'
import { PullRequestOutlined, SyncOutlined, DashboardOutlined, AppstoreOutlined, UnorderedListOutlined, BarChartOutlined, TeamOutlined, ClockCircleOutlined, CheckCircleOutlined, ExclamationCircleOutlined, ThunderboltOutlined, InfoCircleOutlined } from '@ant-design/icons'
import * as hooks from '../hooks/usePRPipeline'
import type { PullRequestResponse, PRPipelineContributor } from '../services/prPipeline'
import dayjs from 'dayjs'
import { BarChart, Bar, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend, ResponsiveContainer, ReferenceLine, Cell } from 'recharts'

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

const METRIC_DEFINITIONS: Record<string, string> = {
  open_count: '当前处于开启状态的 PR 总数（含草稿）',
  merged_count: '已合并的 PR 总数',
  closed_count: '已关闭（未合并）的 PR 总数',
  draft_count: '当前处于草稿状态的 PR 数量',
  backlog_index: '积压指数 = Open(非Draft) PR 数 / 日均合入量。阈值：绿<1.5 / 黄≥1.5 / 红≥3',
  merge_rate: '合并率 = 已合并 PR / (已合并 + 已关闭) × 100%',
  avg_first_review: '从 PR 创建到首次收到 Review 的平均时长',
  avg_merge: '从 PR 创建到合并的平均时长',
  first_response: '首次响应时长：从 PR 创建到首次 Review 的时间',
  review_to_approval: '评审通过时长：从首次 Review 到首次 Approved 的时间',
  ci_duration: 'CI 耗时：从 CI 开始到完成的时间',
  merge_hours: '端到端合入时长：从 PR 创建到合并的时间',
  total_cycle: '总周期：从 PR 创建到合并的完整时长（仅已合并 PR）',
  analyzed_pr_count: '在统计周期内有完整生命周期数据的 PR 数量',
  pr_count: '该作者提交的 PR 总数',
  merged_count_contrib: '该作者已合并的 PR 数',
  lines_added: '该作者新增的代码行数',
  lines_removed: '该作者删除的代码行数',
  review_count: '该评审人参与的 Review 总数',
  avg_first_response_contrib: '该评审人的平均首次响应时长',
}

interface DrillDownFilters {
  state?: string
  author?: string
  pipeline_stage?: string
  review_status?: string
  ci_status?: string
  is_draft?: boolean
  search?: string
}

interface ListTabProps {
  filters: DrillDownFilters
  onFiltersChange: (filters: DrillDownFilters) => void
  page: number
  pageSize: number
  onPageChange: (page: number, pageSize: number) => void
}

const MetricTitle = ({ title, definitionKey }: { title: string; definitionKey?: string }) => {
  if (!definitionKey || !METRIC_DEFINITIONS[definitionKey]) return <>{title}</>
  return (
    <Tooltip title={METRIC_DEFINITIONS[definitionKey]}>
      <span style={{ cursor: 'help', borderBottom: '1px dashed #bbb' }}>
        {title} <InfoCircleOutlined style={{ fontSize: 12, color: '#999' }} />
      </span>
    </Tooltip>
  )
}

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

const renderAvatar = (author: string, avatarUrl: string | null, avatarBase64?: string | null) => (
  <Space size={4}>
    <Avatar size={20} src={avatarBase64 || avatarUrl} style={{ backgroundColor: '#1677ff' }}>
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
  if (index < 1.5) return '#52c41a'
  if (index < 3) return '#faad14'
  return '#ff4d4f'
}

const OverviewTab = ({ period, onDrillDown }: { period: number; onDrillDown: (f: DrillDownFilters) => void }) => {
  const { data, isLoading } = hooks.usePRPipelineOverview(period)

  if (isLoading) return <Spin style={{ display: 'block', margin: '40px auto' }} />
  if (!data) return <Text type="secondary">暂无数据</Text>

  const backlogColor = getBacklogColor(data.backlog_index)

  return (
    <div>
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card hoverable onClick={() => onDrillDown({ state: 'open' })} style={{ cursor: 'pointer' }}>
            <Statistic title={<MetricTitle title="开启" definitionKey="open_count" />} value={data.open_count} prefix={<PullRequestOutlined />} valueStyle={{ color: '#1677ff' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card hoverable onClick={() => onDrillDown({ state: 'merged' })} style={{ cursor: 'pointer' }}>
            <Statistic title={<MetricTitle title="已合并" definitionKey="merged_count" />} value={data.merged_count} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card hoverable onClick={() => onDrillDown({ state: 'closed' })} style={{ cursor: 'pointer' }}>
            <Statistic title={<MetricTitle title="已关闭" definitionKey="closed_count" />} value={data.closed_count} prefix={<ExclamationCircleOutlined />} valueStyle={{ color: '#ff4d4f' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card hoverable onClick={() => onDrillDown({ state: 'open', is_draft: true })} style={{ cursor: 'pointer' }}>
            <Statistic title={<MetricTitle title="草稿" definitionKey="draft_count" />} value={data.draft_count} prefix={<ClockCircleOutlined />} valueStyle={{ color: '#faad14' }} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card hoverable onClick={() => onDrillDown({ state: 'open' })} style={{ cursor: 'pointer' }}>
            <Statistic
              title={<MetricTitle title="积压指数" definitionKey="backlog_index" />}
              value={data.backlog_index}
              suffix="天"
              precision={1}
              valueStyle={{ color: backlogColor }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card hoverable onClick={() => onDrillDown({ state: 'merged' })} style={{ cursor: 'pointer' }}>
            <Statistic
              title={<MetricTitle title="合并率" definitionKey="merge_rate" />}
              value={data.merge_rate * 100}
              suffix="%"
              precision={1}
              valueStyle={{ color: data.merge_rate >= 0.6 ? '#52c41a' : '#faad14' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={<MetricTitle title="平均首次 Review" definitionKey="avg_first_review" />}
              value={formatHours(data.avg_time_to_first_review_hours)}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={<MetricTitle title="平均合并时间" definitionKey="avg_merge" />}
              value={formatHours(data.avg_time_to_merge_hours)}
              prefix={<ThunderboltOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Card title={<MetricTitle title="流水线阶段分布" />} style={{ marginBottom: 24 }}>
        <Space size={[8, 12]} wrap>
          {Object.entries(data.pipeline_stage_distribution || {}).map(([stage, count]: [string, number]) => (
            <Tag
              key={stage}
              color={PIPELINE_STAGE_COLORS[stage] || 'default'}
              style={{ fontSize: 14, padding: '4px 12px', cursor: 'pointer' }}
              onClick={() => onDrillDown({ pipeline_stage: stage, state: 'open' })}
            >
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

const KanbanTab = ({ onDrillDown }: { onDrillDown: (f: DrillDownFilters) => void }) => {
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
                  <Tooltip title="点击查看明细列表">
                    <Badge
                      count={prs.length}
                      style={{ backgroundColor: '#666', cursor: 'pointer' }}
                      onClick={() => onDrillDown({ pipeline_stage: stage })}
                    />
                  </Tooltip>
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

const ListTab = ({ filters, onFiltersChange, page, pageSize, onPageChange }: ListTabProps) => {
  const navigate = useNavigate()

  const stateFilter = filters.state
  const authorFilter = filters.author
  const stageFilter = filters.pipeline_stage
  const searchFilter = filters.search

  const { data, isLoading } = hooks.usePRPipelineList({
    state: stateFilter,
    author: authorFilter,
    pipeline_stage: stageFilter,
    is_draft: filters.is_draft,
    search: searchFilter,
    page,
    page_size: pageSize,
  })

  const updateFilter = (patch: Partial<DrillDownFilters>) => {
    onFiltersChange({ ...filters, ...patch })
  }

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
      title: 'CI 状态/耗时',
      dataIndex: 'ci_status',
      key: 'ci_status',
      width: 130,
      render: (status: string | null, record: PullRequestResponse) => {
        const tag = renderCIStatusTag(status)
        if (!record.ci_started_at && !record.ci_completed_at) {
          return tag
        }
        const tooltipContent = (
          <div>
            {record.ci_started_at && (
              <div>开始: {dayjs(record.ci_started_at).format('YYYY-MM-DD HH:mm:ss')}</div>
            )}
            {record.ci_completed_at && (
              <div>结束: {dayjs(record.ci_completed_at).format('YYYY-MM-DD HH:mm:ss')}</div>
            )}
          </div>
        )
        return (
          <Tooltip title={tooltipContent}>
            <div style={{ cursor: 'help' }}>
              {tag}
              {record.ci_duration_hours != null && (
                <div style={{ fontSize: 11, color: '#999' }}>{formatHours(record.ci_duration_hours)}</div>
              )}
            </div>
          </Tooltip>
        )
      },
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
      {Object.keys(filters).length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <Tag
            closable
            onClose={() => onFiltersChange({})}
            color="blue"
            style={{ cursor: 'pointer' }}
          >
            已应用筛选：点击清除全部
          </Tag>
        </div>
      )}
      <div style={{ marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <Select
          placeholder="状态"
          allowClear
          style={{ width: 120 }}
          value={stateFilter}
          onChange={(v) => updateFilter({ state: v })}
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
          onChange={(e) => updateFilter({ author: e.target.value || undefined })}
        />
        <Select
          placeholder="流水线阶段"
          allowClear
          style={{ width: 150 }}
          value={stageFilter}
          onChange={(v) => updateFilter({ pipeline_stage: v })}
          options={STAGE_COLUMNS.map((s) => ({ value: s, label: STAGE_LABELS[s] }))}
        />
        <Input.Search
          placeholder="搜索 PR"
          allowClear
          style={{ width: 200 }}
          value={searchFilter}
          onChange={(e) => updateFilter({ search: e.target.value || undefined })}
          onSearch={(v) => updateFilter({ search: v || undefined })}
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
          onChange: (p, ps) => onPageChange(p, ps),
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

const MetricsTab = ({ period, onDrillDown }: { period: number; onDrillDown: (f: DrillDownFilters) => void }) => {
  const { data, isLoading } = hooks.usePRPipelineMetrics(period)

  if (isLoading) return <Spin style={{ display: 'block', margin: '40px auto' }} />
  if (!data) return <Text type="secondary">暂无数据</Text>

  const backlogColor = getBacklogColor(data.backlog_index)

  const metricRows = [
    { label: <MetricTitle title="首次响应" definitionKey="first_response" />, key: 'first_response_hours', metric: data.first_response_hours },
    { label: <MetricTitle title="Review → 通过" definitionKey="review_to_approval" />, key: 'review_to_approval_hours', metric: data.review_to_approval_hours },
    { label: <MetricTitle title="CI 耗时" definitionKey="ci_duration" />, key: 'ci_duration_hours', metric: data.ci_duration_hours },
    { label: <MetricTitle title="合并时间" definitionKey="merge_hours" />, key: 'merge_hours', metric: data.merge_hours },
    { label: <MetricTitle title="总周期" definitionKey="total_cycle" />, key: 'total_cycle_hours', metric: data.total_cycle_hours },
  ]

  const shortName: Record<string, string> = {
    first_response_hours: '首次响应',
    review_to_approval_hours: 'Review→通过',
    ci_duration_hours: 'CI耗时',
    merge_hours: '合并时间',
    total_cycle_hours: '总周期',
  }
  const percentileChartData = metricRows.map((r) => ({
    name: shortName[r.key] || r.key,
    P50: r.metric?.p50 ?? 0,
    P90: r.metric?.p90 ?? 0,
    均值: r.metric?.avg ?? 0,
  }))

  const survivalChartData = (data.survival_distribution || []).map((p) => ({ day: p.day, percent: p.cumulative_percent }))
  const p50Day = survivalChartData.find((p) => p.percent >= 50)?.day ?? null
  const p90Day = survivalChartData.find((p) => p.percent >= 90)?.day ?? null

  const slowestChartData = (data.slowest_prs || []).map((p) => ({
    name: `#${p.pr_number} ${p.title.length > 28 ? p.title.slice(0, 28) + '…' : p.title}`,
    hours: p.hours,
  }))

  return (
    <div>
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card hoverable onClick={() => onDrillDown({ state: 'merged' })} style={{ cursor: 'pointer' }}>
            <Statistic
              title={<MetricTitle title="合并率" definitionKey="merge_rate" />}
              value={data.merge_rate * 100}
              suffix="%"
              precision={1}
              valueStyle={{ color: data.merge_rate >= 0.6 ? '#52c41a' : '#faad14' }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card hoverable onClick={() => onDrillDown({ state: 'open' })} style={{ cursor: 'pointer' }}>
            <Statistic
              title={<MetricTitle title="积压指数" definitionKey="backlog_index" />}
              value={data.backlog_index}
              suffix="天"
              precision={1}
              valueStyle={{ color: backlogColor }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card hoverable onClick={() => onDrillDown({ state: 'merged' })} style={{ cursor: 'pointer' }}>
            <Statistic title={<MetricTitle title="已分析 PR 数" definitionKey="analyzed_pr_count" />} value={data.total_cycle_hours?.count || 0} />
          </Card>
        </Col>
      </Row>

      <Card title="百分位指标（小时）" style={{ marginBottom: 24 }}>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={percentileChartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" tick={{ fontSize: 12 }} />
            <YAxis tickFormatter={(v: any) => formatHours(Number(v))} tick={{ fontSize: 12 }} />
            <RechartsTooltip formatter={(v: any) => formatHours(Number(v))} />
            <Legend />
            <Bar dataKey="P50" fill="#1677ff" radius={[3, 3, 0, 0]} />
            <Bar dataKey="P90" fill="#faad14" radius={[3, 3, 0, 0]} />
            <Bar dataKey="均值" fill="#52c41a" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
        <Table
          dataSource={metricRows}
          rowKey="key"
          pagination={false}
          size="small"
          style={{ marginTop: 16 }}
          columns={[
            { title: '指标', dataIndex: 'label', key: 'label', width: 200 },
            { title: 'P50', key: 'p50', width: 100, render: (_, row) => formatHours(row.metric?.p50) },
            { title: 'P90', key: 'p90', width: 100, render: (_, row) => formatHours(row.metric?.p90) },
            { title: '平均值', key: 'avg', width: 100, render: (_, row) => formatHours(row.metric?.avg) },
            { title: '数量', key: 'count', width: 80, render: (_, row) => row.metric?.count || 0 },
          ]}
        />
      </Card>

      {survivalChartData.length > 0 && (
        <Card title="存活分布（累计合并率）" style={{ marginBottom: 24 }}>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={survivalChartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="survivalGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#1677ff" stopOpacity={0.6} />
                  <stop offset="100%" stopColor="#1677ff" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="day" tickFormatter={(d: any) => `${d}d`} tick={{ fontSize: 12 }} />
              <YAxis domain={[0, 100]} tickFormatter={(v: any) => `${v}%`} tick={{ fontSize: 12 }} />
              <RechartsTooltip formatter={(v: any) => `${Math.round(Number(v))}%`} labelFormatter={(d: any) => `${d} 天内`} />
              <Area type="monotone" dataKey="percent" stroke="#1677ff" fill="url(#survivalGrad)" name="累计合并率" />
              {p50Day !== null && <ReferenceLine x={p50Day} stroke="#52c41a" strokeDasharray="4 4" label={{ value: `P50 ${p50Day}d`, position: 'top', fill: '#52c41a', fontSize: 11 }} />}
              {p90Day !== null && <ReferenceLine x={p90Day} stroke="#faad14" strokeDasharray="4 4" label={{ value: `P90 ${p90Day}d`, position: 'top', fill: '#faad14', fontSize: 11 }} />}
            </AreaChart>
          </ResponsiveContainer>
        </Card>
      )}

      {slowestChartData.length > 0 && (
        <Card title="最慢合并 PR Top 10（created → merged）" style={{ marginBottom: 24 }}>
          <ResponsiveContainer width="100%" height={Math.max(260, slowestChartData.length * 34)}>
            <BarChart data={slowestChartData} layout="vertical" margin={{ top: 8, right: 24, left: 8, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tickFormatter={(v: any) => formatHours(Number(v))} tick={{ fontSize: 12 }} />
              <YAxis type="category" dataKey="name" width={240} tick={{ fontSize: 11 }} />
              <RechartsTooltip formatter={(v: any) => formatHours(Number(v))} />
              <Bar dataKey="hours" name="合并耗时" radius={[0, 3, 3, 0]}>
                {slowestChartData.map((entry, i) => (
                  <Cell key={i} fill={entry.hours >= 72 ? '#ff4d4f' : entry.hours >= 24 ? '#faad14' : '#52c41a'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>
      )}
    </div>
  )
}

const ContributorsTab = ({ period, onDrillDown }: { period: number; onDrillDown: (f: DrillDownFilters) => void }) => {
  const [contributorType, setContributorType] = useState<string | undefined>(undefined)
  const [companyFilter, setCompanyFilter] = useState<string | undefined>(undefined)
  const [page, setPage] = useState(1)
  const pageSize = 20
  const skip = (page - 1) * pageSize
  const { data, isLoading } = hooks.usePRPipelineContributors(period, contributorType, skip, pageSize, companyFilter)

  if (isLoading) return <Spin style={{ display: 'block', margin: '40px auto' }} />

  const items = data?.items || []
  const total = data?.total || 0
  const authors = items.filter((c: PRPipelineContributor) => c.type === 'author' || c.pr_count > 0)
  const reviewers = items.filter((c: PRPipelineContributor) => c.type === 'reviewer' || c.review_count > 0)

  const authorColumns = [
    {
      title: '作者',
      key: 'username',
      width: 180,
      render: (_: unknown, record: PRPipelineContributor) => renderAvatar(record.username, record.avatar_url, record.avatar_base64),
    },
    {
      title: '公司',
      key: 'company',
      width: 80,
      render: (_: unknown, record: PRPipelineContributor) => {
        if (!record.company) return <Text type="secondary">—</Text>
        return <Tag color="blue">{record.company}</Tag>
      },
    },
    {
      title: <MetricTitle title="PR 数量" definitionKey="pr_count" />,
      dataIndex: 'pr_count',
      key: 'pr_count',
      width: 100,
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => a.pr_count - b.pr_count,
      render: (val: number, record: PRPipelineContributor) => (
        <a onClick={() => onDrillDown({ author: record.username })}>{val}</a>
      ),
    },
    {
      title: <MetricTitle title="已合并" definitionKey="merged_count_contrib" />,
      dataIndex: 'merged_count',
      key: 'merged_count',
      width: 100,
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => a.merged_count - b.merged_count,
      render: (val: number, record: PRPipelineContributor) => (
        <a onClick={() => onDrillDown({ author: record.username, state: 'merged' })}>{val}</a>
      ),
    },
    {
      title: <MetricTitle title="新增行数" definitionKey="lines_added" />,
      dataIndex: 'lines_added',
      key: 'lines_added',
      width: 120,
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => a.lines_added - b.lines_added,
    },
    {
      title: <MetricTitle title="删除行数" definitionKey="lines_removed" />,
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
      render: (_: unknown, record: PRPipelineContributor) => renderAvatar(record.username, record.avatar_url, record.avatar_base64),
    },
    {
      title: '公司',
      key: 'company',
      width: 80,
      render: (_: unknown, record: PRPipelineContributor) => {
        if (!record.company) return <Text type="secondary">—</Text>
        return <Tag color="blue">{record.company}</Tag>
      },
    },
    {
      title: <MetricTitle title="Review 数量" definitionKey="review_count" />,
      dataIndex: 'review_count',
      key: 'review_count',
      width: 120,
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => a.review_count - b.review_count,
    },
    {
      title: <MetricTitle title="平均首次响应" definitionKey="avg_first_response_contrib" />,
      dataIndex: 'avg_first_response_hours',
      key: 'avg_first_response_hours',
      width: 150,
      render: (hours: number | null) => formatHours(hours),
      sorter: (a: PRPipelineContributor, b: PRPipelineContributor) => (a.avg_first_response_hours || 0) - (b.avg_first_response_hours || 0),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
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
        <Select
          placeholder="公司筛选"
          allowClear
          style={{ width: 150 }}
          value={companyFilter}
          onChange={(val) => { setCompanyFilter(val); setPage(1); }}
          options={[
            { value: '华为', label: '华为' },
            { value: 'none', label: '未标注' },
          ]}
        />
      </div>

      {(!contributorType || contributorType === 'author') && (
        <Card title="作者" style={{ marginBottom: 24 }}>
          <Table
            columns={authorColumns}
            dataSource={authors}
            loading={isLoading}
            rowKey="username"
            pagination={contributorType === 'author' ? {
              current: page,
              pageSize,
              total,
              onChange: (p) => setPage(p),
              showSizeChanger: false,
            } : false}
          />
        </Card>
      )}

      {(!contributorType || contributorType === 'reviewer') && (
        <Card title="评审人">
          <Table
            columns={reviewerColumns}
            dataSource={reviewers}
            loading={isLoading}
            rowKey="username"
            pagination={contributorType === 'reviewer' ? {
              current: page,
              pageSize,
              total,
              onChange: (p) => setPage(p),
              showSizeChanger: false,
            } : false}
          />
        </Card>
      )}
    </div>
  )
}

const SyncButton = () => {
  const syncMutation = hooks.usePRPipelineSync()
  const { data: syncStatus } = hooks.usePRPipelineSyncStatus()
  const isSyncing = syncStatus?.running || syncMutation.isPending

  const handleSync = () => {
    if (isSyncing) {
      message.warning('同步正在进行中，请稍候')
      return
    }
    syncMutation.mutate(undefined, {
      onSuccess: (data) => {
        if (data?.running) {
          message.warning('同步正在进行中，请稍候')
        } else {
          message.success(data?.message || '同步已开始')
        }
      },
      onError: (error: any) => {
        message.error(error?.response?.data?.detail || '同步失败')
      },
    })
  }

  return (
    <Button
      icon={<SyncOutlined />}
      loading={isSyncing}
      disabled={isSyncing}
      onClick={handleSync}
    >
      {isSyncing ? '同步中...' : '同步数据'}
    </Button>
  )
}

const PRPipelineBoard = () => {
  const [activeTab, setActiveTab] = useState('overview')
  const [overviewPeriod, setOverviewPeriod] = useState(30)
  const [metricsPeriod, setMetricsPeriod] = useState(30)
  const [contributorsPeriod, setContributorsPeriod] = useState(30)
  const [listFilters, setListFilters] = useState<DrillDownFilters>({})
  const [listPage, setListPage] = useState(1)
  const [listPageSize, setListPageSize] = useState(20)

  const handleDrillDown = (filters: DrillDownFilters) => {
    setListFilters(filters)
    setListPage(1)
    setActiveTab('list')
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
          <OverviewTab period={overviewPeriod} onDrillDown={handleDrillDown} />
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
      children: <KanbanTab onDrillDown={handleDrillDown} />,
    },
    {
      key: 'list',
      label: (
          <Space>
            <UnorderedListOutlined />
            <span>列表</span>
          </Space>
      ),
      children: (
        <ListTab
          filters={listFilters}
          onFiltersChange={(f) => { setListFilters(f); setListPage(1) }}
          page={listPage}
          pageSize={listPageSize}
          onPageChange={(p, ps) => { setListPage(p); setListPageSize(ps) }}
        />
      ),
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
          <MetricsTab period={metricsPeriod} onDrillDown={handleDrillDown} />
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
          <ContributorsTab period={contributorsPeriod} onDrillDown={handleDrillDown} />
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
        <SyncButton />
      </div>

      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
    </div>
  )
}

export default PRPipelineBoard
