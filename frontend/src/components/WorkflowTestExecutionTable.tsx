import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button,
  Card,
  DatePicker,
  Empty,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  EyeOutlined,
  GithubOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import { useJobs, useWorkflows } from '../hooks/useCI'
import { useFailureAnalysisList } from '../hooks/useFailureAnalysis'
import type { CIJob, StepSummary } from '../services/ci'
import { PROBLEM_CATEGORY_MAP } from '../services/failureAnalysis'
import {
  formatDuration,
  renderConclusionTag,
  renderHardwareTag,
  renderStatusTag,
} from '../utils/ciRenderers'
import { formatTimezone, fromTimezoneNow } from '../utils/timezone'

const { Text } = Typography
const { RangePicker } = DatePicker

interface WorkflowTestExecutionTableProps {
  enabled: boolean
}

const STATUS_FILTERS = [
  { text: '已完成', value: 'completed' },
  { text: '进行中', value: 'in_progress' },
  { text: '等待中', value: 'queued' },
]

const RESULT_FILTERS = [
  { text: '成功', value: 'success' },
  { text: '失败', value: 'failure' },
  { text: '取消', value: 'cancelled' },
  { text: '跳过', value: 'skipped' },
]

const getDefaultDateRange = (): [Dayjs, Dayjs] => {
  const today = dayjs()
  return [today.startOf('day'), today.endOf('day')]
}

type WorkflowExecutionPreferences = {
  workflowFilter?: string[]
  selectedWorkflow?: string | null
  hardwareFilter?: string[]
  statusFilter?: string[]
  resultFilter?: string[]
  logSearch?: string
  dateRange?: { start: string | null; end: string | null } | null
}

const DEFAULT_WORKFLOW = 'Nightly-A3'
const WORKFLOW_EXECUTION_PREFERENCES_KEY = 'ci-workflow-execution-preferences'

function readWorkflowExecutionPreferences(): WorkflowExecutionPreferences {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(WORKFLOW_EXECUTION_PREFERENCES_KEY)
    return raw ? JSON.parse(raw) as WorkflowExecutionPreferences : {}
  } catch {
    return {}
  }
}

const toJobStatus = (job: CIJob) => job.status || (job.completed_at ? 'completed' : 'in_progress')

const renderSteps = (steps: StepSummary[] | null | undefined) => {
  if (!steps || steps.length === 0) return '-'
  const successCount = steps.filter((step) => step.conclusion === 'success').length
  const failureCount = steps.filter((step) => step.conclusion === 'failure').length
  const skippedCount = steps.filter((step) => step.conclusion === 'skipped').length

  return (
    <Space size="small">
      {successCount > 0 && <Tag color="success" icon={<CheckCircleOutlined />}>{successCount}</Tag>}
      {failureCount > 0 && <Tag color="error" icon={<CloseCircleOutlined />}>{failureCount}</Tag>}
      {skippedCount > 0 && <Tag color="default">{skippedCount}</Tag>}
    </Space>
  )
}

function WorkflowTestExecutionTable({ enabled }: WorkflowTestExecutionTableProps) {
  const navigate = useNavigate()
  const [savedPreferences] = useState(readWorkflowExecutionPreferences)
  const initialWorkflow = savedPreferences.selectedWorkflow || savedPreferences.workflowFilter?.[0] || DEFAULT_WORKFLOW
  const [workflowFilter, setWorkflowFilter] = useState<string[]>(() => savedPreferences.workflowFilter?.length ? savedPreferences.workflowFilter : [initialWorkflow])
  const [selectedWorkflow, setSelectedWorkflow] = useState<string | undefined>(() => initialWorkflow)
  const [hardwareFilter, setHardwareFilter] = useState<string[]>(() => savedPreferences.hardwareFilter ?? [])
  const [statusFilter, setStatusFilter] = useState<string[]>(() => savedPreferences.statusFilter ?? [])
  const [resultFilter, setResultFilter] = useState<string[]>(() => savedPreferences.resultFilter ?? [])
  const [logSearch, setLogSearch] = useState(() => savedPreferences.logSearch ?? '')
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(() => {
    const savedRange = savedPreferences.dateRange
    if (savedRange === null) return null
    if (savedRange?.start || savedRange?.end) {
      return [
        savedRange.start ? dayjs(savedRange.start) : null,
        savedRange.end ? dayjs(savedRange.end) : null,
      ]
    }
    return getDefaultDateRange()
  })

  useEffect(() => {
    window.localStorage.setItem(WORKFLOW_EXECUTION_PREFERENCES_KEY, JSON.stringify({
      workflowFilter,
      selectedWorkflow: selectedWorkflow ?? null,
      hardwareFilter,
      statusFilter,
      resultFilter,
      logSearch,
      dateRange: dateRange
        ? {
            start: dateRange[0]?.format('YYYY-MM-DD') ?? null,
            end: dateRange[1]?.format('YYYY-MM-DD') ?? null,
          }
        : null,
    } satisfies WorkflowExecutionPreferences))
  }, [workflowFilter, selectedWorkflow, hardwareFilter, statusFilter, resultFilter, logSearch, dateRange])

  const workflowsQuery = useWorkflows()
  const jobsQuery = useJobs({
    days: 30,
    limit: 500,
    workflow_name: selectedWorkflow,
  }, enabled)
  const analysisQuery = useFailureAnalysisList({ days_back: 30 }, enabled)
  const jobs = jobsQuery.data || []
  const analysisMap = useMemo(() => (
    new Map((analysisQuery.data?.items || []).map((analysis) => [analysis.job_id, analysis]))
  ), [analysisQuery.data?.items])

  const workflowOptions = useMemo(() => (
    Array.from(new Set([
      ...(workflowsQuery.data || []),
      ...jobs.map((job) => job.workflow_name),
    ].filter(Boolean)))
      .map((workflowName) => ({ text: workflowName, value: workflowName }))
  ), [jobs, workflowsQuery.data])

  const hardwareOptions = useMemo(() => (
    Array.from(new Set(jobs.map((job) => job.hardware).filter(Boolean)))
      .map((hardware) => ({ text: hardware as string, value: hardware as string }))
  ), [jobs])

  const visibleJobs = useMemo(() => {
    const keyword = logSearch.trim().toLowerCase()
    return jobs.filter((job) => {
      const analysis = analysisMap.get(job.job_id)
      if (selectedWorkflow && job.workflow_name !== selectedWorkflow) return false
      if (workflowFilter.length > 0 && !workflowFilter.includes(job.workflow_name)) return false
      if (hardwareFilter.length > 0 && !hardwareFilter.includes(job.hardware || '')) return false
      if (statusFilter.length > 0 && !statusFilter.includes(toJobStatus(job))) return false
      if (resultFilter.length > 0 && !resultFilter.includes(job.conclusion || '')) return false
      if (dateRange) {
        const [start, end] = dateRange
        if (!job.started_at) return false
        const startedAt = dayjs(formatTimezone(job.started_at, 'YYYY-MM-DD'))
        if (start && startedAt.isBefore(start.startOf('day'))) return false
        if (end && startedAt.isAfter(end.endOf('day'))) return false
      }
      if (!keyword) return true
      return [
        job.workflow_name,
        job.job_name,
        job.runner_name,
        analysis?.problem_category,
        analysis?.root_cause_summary,
        analysis?.improvement_measures_summary,
      ].some((value) => value?.toLowerCase().includes(keyword))
    })
  }, [analysisMap, dateRange, hardwareFilter, jobs, logSearch, resultFilter, selectedWorkflow, statusFilter, workflowFilter])

  const columns = [
    {
      title: 'Workflow',
      dataIndex: 'workflow_name',
      key: 'workflow_name',
      width: 190,
      filters: workflowOptions,
      filteredValue: workflowFilter,
      onFilter: (value: boolean | React.Key, record: CIJob) => record.workflow_name === value,
      render: (value: string) => <Tag color="blue">{value || '-'}</Tag>,
    },
    {
      title: 'Job 名称',
      dataIndex: 'job_name',
      key: 'job_name',
      width: 280,
      ellipsis: true,
      render: (value: string, record: CIJob) => (
        <Tooltip title={record.runner_name ? `Runner: ${record.runner_name}` : value} placement="topLeft">
          <Space direction="vertical" size={0}>
            <Text strong ellipsis>{value || '-'}</Text>
            {record.runner_name && <Text type="secondary" style={{ fontSize: 12 }} ellipsis>Runner: {record.runner_name}</Text>}
          </Space>
        </Tooltip>
      ),
    },
    {
      title: '硬件',
      dataIndex: 'hardware',
      key: 'hardware',
      width: 100,
      filters: hardwareOptions,
      filteredValue: hardwareFilter,
      onFilter: (value: boolean | React.Key, record: CIJob) => record.hardware === value,
      render: renderHardwareTag,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      filters: STATUS_FILTERS,
      filteredValue: statusFilter,
      onFilter: (value: boolean | React.Key, record: CIJob) => toJobStatus(record) === value,
      render: (_: string, record: CIJob) => renderStatusTag(toJobStatus(record)),
    },
    {
      title: '结果',
      dataIndex: 'conclusion',
      key: 'conclusion',
      width: 100,
      filters: RESULT_FILTERS,
      filteredValue: resultFilter,
      onFilter: (value: boolean | React.Key, record: CIJob) => record.conclusion === value,
      render: renderConclusionTag,
    },
    {
      title: '时长',
      dataIndex: 'duration_seconds',
      key: 'duration_seconds',
      width: 100,
      render: formatDuration,
    },
    {
      title: '开始时间',
      dataIndex: 'started_at',
      key: 'started_at',
      width: 180,
      sorter: (a: CIJob, b: CIJob) => new Date(b.started_at || 0).getTime() - new Date(a.started_at || 0).getTime(),
      render: (startedAt: string | null) => startedAt ? (
        <Space direction="vertical" size={0}>
          <Text>{formatTimezone(startedAt, 'YYYY-MM-DD HH:mm:ss')}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{fromTimezoneNow(startedAt)}</Text>
        </Space>
      ) : '-',
    },
    {
      title: 'Steps',
      key: 'steps',
      width: 120,
      render: (_: unknown, record: CIJob) => renderSteps(record.steps_summary),
    },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_: unknown, record: CIJob) => (
        <Space>
          <Button type="link" icon={<EyeOutlined />} onClick={() => navigate(`/ci/jobs/${record.job_id}`)} style={{ padding: 0 }}>
            详情
          </Button>
          {record.github_job_url && (
            <a href={record.github_job_url} target="_blank" rel="noopener noreferrer" onClick={(event) => event.stopPropagation()}>
              <GithubOutlined />
            </a>
          )}
        </Space>
      ),
    },
    {
      title: '问题分类',
      key: 'problem_category',
      width: 120,
      render: (_: unknown, record: CIJob) => {
        const category = analysisMap.get(record.job_id)?.problem_category
        if (!category) return '-'
        const categoryInfo = PROBLEM_CATEGORY_MAP[category] || { color: '#64748d', label: category }
        return <Tag color={categoryInfo.color}>{categoryInfo.label}</Tag>
      },
    },
    {
      title: '根因摘要',
      key: 'root_cause_summary',
      width: 220,
      ellipsis: true,
      render: (_: unknown, record: CIJob) => {
        const summary = analysisMap.get(record.job_id)?.root_cause_summary
        return summary ? <Tooltip title={summary}><Text ellipsis style={{ maxWidth: 200 }}>{summary}</Text></Tooltip> : '-'
      },
    },
    {
      title: '改进建议',
      key: 'improvement_measures_summary',
      width: 220,
      ellipsis: true,
      render: (_: unknown, record: CIJob) => {
        const measures = analysisMap.get(record.job_id)?.improvement_measures_summary
        return measures ? <Tooltip title={measures}><Text ellipsis style={{ maxWidth: 200 }}>{measures}</Text></Tooltip> : '-'
      },
    },
  ]

  const resetFilters = () => {
    setWorkflowFilter([DEFAULT_WORKFLOW])
    setSelectedWorkflow(DEFAULT_WORKFLOW)
    setHardwareFilter([])
    setStatusFilter([])
    setResultFilter([])
    setLogSearch('')
    setDateRange(getDefaultDateRange())
  }

  const isDefaultDateRange = Boolean(
    dateRange?.[0]?.isSame(dayjs(), 'day') && dateRange?.[1]?.isSame(dayjs(), 'day'),
  )
  const hasFilters = Boolean(
    workflowFilter.length || hardwareFilter.length || statusFilter.length || resultFilter.length || logSearch || !isDefaultDateRange,
  )

  const handleRefresh = async () => {
    await Promise.all([jobsQuery.refetch(), analysisQuery.refetch()])
  }

  return (
    <Card
      title="运行记录"
      extra={(
        <Space>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            value={selectedWorkflow}
            options={workflowOptions.map(({ text, value }) => ({ label: text, value }))}
            onChange={(value) => {
              setSelectedWorkflow(value)
              setWorkflowFilter(value ? [value] : [])
            }}
            placeholder="按 Workflow 筛选"
            style={{ width: 190 }}
          />
          <RangePicker
            value={dateRange as any}
            onChange={(dates) => setDateRange(dates as [Dayjs | null, Dayjs | null] | null)}
            allowClear
            format="YYYY-MM-DD"
            placeholder={['开始日期', '结束日期']}
          />
          <Input.Search
            allowClear
            value={logSearch}
            onChange={(event) => setLogSearch(event.target.value)}
            placeholder="搜索 Workflow、Job 或日志"
            style={{ width: 250 }}
          />
          <Button icon={<ReloadOutlined />} onClick={handleRefresh} loading={jobsQuery.isLoading || analysisQuery.isLoading}>刷新</Button>
          <Button onClick={resetFilters} disabled={!hasFilters}>重置筛选</Button>
        </Space>
      )}
    >
      <Table
        columns={columns}
        dataSource={visibleJobs}
        loading={jobsQuery.isLoading || analysisQuery.isLoading}
        rowKey={(record) => `${record.job_id}-${record.id}`}
        pagination={{ pageSize: 20, showSizeChanger: false, showTotal: (total) => `共 ${total} 条` }}
        scroll={{ x: 2000 }}
        locale={{ emptyText: <Empty description="暂无运行记录" /> }}
        onChange={(_, filters) => {
          const nextWorkflowFilter = (filters.workflow_name as string[] | null) || []
          setWorkflowFilter(nextWorkflowFilter)
          setSelectedWorkflow(nextWorkflowFilter.length === 1 ? nextWorkflowFilter[0] : undefined)
          setHardwareFilter((filters.hardware as string[] | null) || [])
          setStatusFilter((filters.status as string[] | null) || [])
          setResultFilter((filters.conclusion as string[] | null) || [])
        }}
      />
    </Card>
  )
}

export default WorkflowTestExecutionTable
