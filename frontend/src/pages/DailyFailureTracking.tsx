import { useState, useMemo } from 'react'
import {
  Card,
  Table,
  Tag,
  Select,
  Space,
  Typography,
  Button,
  Row,
  Col,
  Statistic,
  Modal,
  Input,
  message,
  Tooltip,
  DatePicker,
} from 'antd'
import {
  ReloadOutlined,
  EditOutlined,
  GithubOutlined,
  UserOutlined,
  ExclamationCircleOutlined,
  CheckCircleOutlined,
  SyncOutlined,
  CloseCircleOutlined,
  CheckSquareOutlined,
} from '@ant-design/icons'
import { useDailyFailures, useUpdateFailureStatus, useBatchUpdateFailureStatus } from '../hooks/useCI'
import { formatDuration, renderHardwareTag } from '../utils/ciRenderers'
import { formatTimezone, fromTimezoneNow } from '../utils/timezone'
import type { DailyFailureJob } from '../services/ci'
import dayjs, { Dayjs } from 'dayjs'

const { RangePicker } = DatePicker
const { Search } = Input
const { Text, Title } = Typography
const { TextArea } = Input

const STATUS_CONFIG: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  '未处理': { color: '#ff4d4f', icon: <ExclamationCircleOutlined />, label: '未处理' },
  '处理中': { color: '#fa8c16', icon: <SyncOutlined spin />, label: '处理中' },
  '已关闭': { color: '#8c8c8c', icon: <CloseCircleOutlined />, label: '已关闭' },
}

const PROBLEM_CATEGORIES = ['基础设施', '测试框架', '开发代码', '测试用例', '不稳定用例']

const jobColumns = [
  {
    title: '日期',
    dataIndex: '_date',
    key: '_date',
    width: 110,
    fixed: 'left' as const,
    render: (date: string) => <Text strong>{date}</Text>,
  },
  {
    title: 'Workflow',
    dataIndex: 'workflow_name',
    key: 'workflow_name',
    width: 130,
    ellipsis: true,
    render: (text: string) => <Tag color="blue">{text}</Tag>,
  },
  {
    title: 'Job',
    dataIndex: 'job_name',
    key: 'job_name',
    width: 220,
    ellipsis: true,
    render: (text: string, record: DailyFailureJob) => (
      <Tooltip title={text}>
        <Space direction="vertical" size={0}>
          <Text strong ellipsis style={{ maxWidth: 200 }}>{text}</Text>
          {record.display_name && (
            <Text style={{ fontSize: 12, color: '#1677ff' }}>{record.display_name}</Text>
          )}
        </Space>
      </Tooltip>
    ),
  },
  {
    title: '硬件',
    dataIndex: 'hardware',
    key: 'hardware',
    width: 60,
    render: renderHardwareTag,
  },
  {
    title: '责任人',
    dataIndex: 'owner',
    key: 'owner',
    width: 90,
    render: (owner: string | null) => {
      if (!owner) return <Text type="secondary">-</Text>
      return (
        <Space size={4}>
          <UserOutlined style={{ color: '#1677ff' }} />
          <Text>{owner}</Text>
        </Space>
      )
    },
  },
  {
    title: '模型 FO',
    dataIndex: 'model_fo',
    key: 'model_fo',
    width: 80,
    render: (text: string | null) => text || '-',
  },
  {
    title: '部署方式',
    dataIndex: 'deployment_type',
    key: 'deployment_type',
    width: 100,
    ellipsis: true,
    render: (text: string | null) => text || '-',
  },
  {
    title: '问题分类',
    dataIndex: 'problem_category',
    key: 'problem_category',
    width: 100,
    render: (text: string | null) => text ? <Tag>{text}</Tag> : <Text type="secondary">-</Text>,
  },
  {
    title: 'PR',
    dataIndex: 'related_pr',
    key: 'related_pr',
    width: 70,
    render: (text: string | null) => text ? <a href={`https://github.com/vllm-project/vllm-ascend/pull/${text}`} target="_blank" rel="noopener noreferrer">#{text}</a> : <Text type="secondary">-</Text>,
  },
  {
    title: '处理状态',
    key: 'processing_status',
    width: 90,
    render: (_: any, record: DailyFailureJob) => {
      const config = STATUS_CONFIG[record.processing_status] || STATUS_CONFIG['未处理']
      return (
        <Tooltip title={`${record.updated_by || '-'} · ${record.status_updated_at ? formatTimezone(record.status_updated_at, 'MM-DD HH:mm') : '-'}`}>
          <Tag color={config.color} icon={config.icon}>{config.label}</Tag>
        </Tooltip>
      )
    },
  },
  {
    title: '备注',
    dataIndex: 'notes',
    key: 'notes',
    width: 160,
    ellipsis: true,
    render: (notes: string | null) => {
      if (!notes) return <Text type="secondary">-</Text>
      return (
        <Tooltip title={notes}>
          <Text ellipsis style={{ maxWidth: 140 }}>{notes}</Text>
        </Tooltip>
      )
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    render: (_: any, record: DailyFailureJob) => (
      <Space size={4}>
        <Button type="link" size="small" icon={<EditOutlined />}
          onClick={(e) => {
            e.stopPropagation()
            ;(window as any).__openEditDailyFailure?.(record)
          }}>
          更新
        </Button>
        {record.github_job_url && (
          <a href={record.github_job_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>
            <Button type="link" size="small" icon={<GithubOutlined />} />
          </a>
        )}
      </Space>
    ),
  },
]

function DailyFailureTracking() {
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>([dayjs(), dayjs()])
  const [workflowFilter, setWorkflowFilter] = useState<string | undefined>('Nightly-A3')
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)
  const [notesSearch, setNotesSearch] = useState<string | undefined>(undefined)
  const [editingJob, setEditingJob] = useState<DailyFailureJob | null>(null)
  const [editStatus, setEditStatus] = useState<string>('未处理')
  const [editProblemCategory, setEditProblemCategory] = useState<string>('')
  const [editRelatedPr, setEditRelatedPr] = useState<string>('')
  const [editNotes, setEditNotes] = useState<string>('')

  const startDate = dateRange?.[0]?.format('YYYY-MM-DD')
  const endDate = dateRange?.[1]?.format('YYYY-MM-DD')

  const { data, isLoading, refetch } = useDailyFailures({
    start_date: startDate,
    end_date: endDate,
    workflow_name: workflowFilter,
    processing_status: statusFilter,
    notes_search: notesSearch,
  })

  const updateMutation = useUpdateFailureStatus()
  const batchUpdateMutation = useBatchUpdateFailureStatus()
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  // Expose edit handler to column renderers
  ;(window as any).__openEditDailyFailure = (job: DailyFailureJob) => {
    setEditingJob(job)
    setEditStatus(job.processing_status)
    setEditProblemCategory(job.problem_category || ''); setEditRelatedPr(job.related_pr || '')
    setEditNotes(job.notes || '')
  }

  const handleSaveStatus = async () => {
    if (!editingJob) return
    try {
      await updateMutation.mutateAsync({
        jobDbId: editingJob.id,
        data: { processing_status: editStatus, problem_category: editProblemCategory || null, related_pr: editRelatedPr || null, notes: editNotes || null },
      })
      message.success('处理状态已更新')
      setEditingJob(null)
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '更新失败')
    }
  }

  // Aggregate stats across all days
  const totalStats = useMemo(() => {
    if (!data || data.length === 0) return { total: 0, unprocessed: 0, processing: 0, fixed: 0, closed: 0 }
    return data.reduce(
      (acc, day) => {
        acc.total += day.stats.total_failed_jobs
        acc.unprocessed += day.stats.unprocessed
        acc.processing += day.stats.processing
        acc.fixed += day.stats.fixed
        acc.closed += day.stats.closed
        return acc
      },
      { total: 0, unprocessed: 0, processing: 0, fixed: 0, closed: 0 }
    )
  }, [data])

  const allJobs = useMemo(() => {
    if (!data) return []
    return data.flatMap(day => day.jobs.map(job => ({ ...job, _date: day.date })))
  }, [data])

  const workflowOptions = useMemo(() => {
    if (!data) return []
    const workflows = new Set<string>()
    data.forEach(day => day.jobs.forEach(job => workflows.add(job.workflow_name)))
    return Array.from(workflows)
  }, [data])

  return (
    <div>
      {/* 标题和操作区 */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>每日失败追踪</Title>
          <Text type="secondary">按天查看失败 Job，追踪处理进展与责任人</Text>
        </div>
        <Space>
          <RangePicker
            value={dateRange as any}
            onChange={(dates) => setDateRange(dates as [Dayjs | null, Dayjs | null] | null)}
            allowClear
            placeholder={['开始日期', '结束日期']}
            format="YYYY-MM-DD"
            style={{ width: 260 }}
          />
          <Search
            placeholder="搜索备注..."
            allowClear
            onSearch={(value) => setNotesSearch(value || undefined)}
            onChange={(e) => { if (!e.target.value) setNotesSearch(undefined) }}
            style={{ width: 180 }}
          />
          <Select
            value={statusFilter}
            onChange={setStatusFilter}
            allowClear
            placeholder="处理状态"
            options={Object.entries(STATUS_CONFIG).map(([v, c]) => ({ label: c.label, value: v }))}
            style={{ width: 120 }}
          />
          <Select
            value={workflowFilter}
            onChange={setWorkflowFilter}
            allowClear
            placeholder="Workflow"
            options={workflowOptions.map(wf => ({ label: wf, value: wf }))}
            style={{ width: 160 }}
          />
          <Button icon={<ReloadOutlined />} onClick={() => refetch()}>刷新</Button>
        </Space>
      </div>

      {/* 总览统计 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={4}>
          <Card size="small">
            <Statistic title="失败总数" value={totalStats.total} suffix="个" valueStyle={{ color: '#ff4d4f' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="未处理" value={totalStats.unprocessed} suffix="个" valueStyle={{ color: '#ff4d4f' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="处理中" value={totalStats.processing} suffix="个" valueStyle={{ color: '#fa8c16' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="已关闭" value={totalStats.closed} suffix="个" valueStyle={{ color: '#8c8c8c' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="处理率"
              value={totalStats.total > 0 ? Math.round(totalStats.closed / totalStats.total * 100) : 0}
              suffix="%"
              valueStyle={{ color: totalStats.total > 0 && totalStats.closed / totalStats.total >= 0.8 ? '#3f8600' : '#cf1322' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 按天分组的折叠面板 */}
      <Card>
        {selectedRowKeys.length > 0 && (
          <div style={{ marginBottom: 12, padding: '8px 12px', background: '#e6f4ff', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 12 }}>
            <Text strong>已选 {selectedRowKeys.length} 条</Text>
            <Select
              placeholder="批量更新状态"
              style={{ width: 140 }}
              onChange={(value) => {
                batchUpdateMutation.mutate(
                  { ids: selectedRowKeys as number[], data: { processing_status: value } },
                  { onSuccess: () => { message.success(`已更新 ${selectedRowKeys.length} 条`); setSelectedRowKeys([]) },
                    onError: (e: any) => message.error(e?.response?.data?.detail || '失败') }
                )
              }}
              options={Object.entries(STATUS_CONFIG).map(([v, c]) => ({ label: c.label, value: v }))}
            />
            <Button size="small" onClick={() => setSelectedRowKeys([])}>取消选择</Button>
          </div>
        )}
        <Table
          columns={jobColumns}
          dataSource={allJobs}
          loading={isLoading}
          rowKey={(record) => `${record._date}-${record.id}`}
          rowSelection={{
            selectedRowKeys,
            onChange: setSelectedRowKeys,
          }}
          pagination={{
            pageSize: 30,
            showSizeChanger: false,
            showTotal: (total) => `共 ${total} 条记录`,
          }}
          scroll={{ x: 1400 }}
          size="middle"
        />
      </Card>

      {/* 编辑处理状态弹窗 */}
      <Modal
        title={<Space><EditOutlined /><span>更新处理状态</span></Space>}
        open={!!editingJob}
        onOk={handleSaveStatus}
        onCancel={() => setEditingJob(null)}
        confirmLoading={updateMutation.isPending}
        okText="保存"
        cancelText="取消"
        width={480}
      >
        {editingJob && (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <div>
              <Text strong>{editingJob.workflow_name}</Text>
              <Text type="secondary"> / </Text>
              <Text>{editingJob.job_name}</Text>
              {editingJob.display_name && (
                <div><Text style={{ fontSize: 12, color: '#1677ff' }}>{editingJob.display_name}</Text></div>
              )}
            </div>
            <div>
              <Text type="secondary">责任人：</Text>
              <Text>{editingJob.owner || '未配置'}</Text>
            </div>
            <div>
              <Text type="secondary">失败时间：</Text>
              <Text>{editingJob.started_at ? formatTimezone(editingJob.started_at, 'YYYY-MM-DD HH:mm:ss') : '-'}</Text>
            </div>
            <div>
              <Text type="secondary">处理状态：</Text>
              <Select
                value={editStatus}
                onChange={setEditStatus}
                style={{ width: '100%', marginTop: 4 }}
                options={Object.entries(STATUS_CONFIG).map(([value, config]) => ({
                  label: <Space>{config.icon}<span>{config.label}</span></Space>,
                  value,
                }))}
              />
            </div>
            <div>
              <Text type="secondary">问题分类：</Text>
              <Select
                value={editProblemCategory || undefined}
                onChange={(v) => setEditProblemCategory(v)}
                placeholder="选择问题分类"
                allowClear
                style={{ width: '100%', marginTop: 4 }}
                options={PROBLEM_CATEGORIES.map(c => ({ label: c, value: c }))}
              />
            </div>
            <div>
              <Text type="secondary">关联 PR{editProblemCategory === '开发代码' ? ' (必填)' : ''}：</Text>
              <Input
                value={editRelatedPr}
                onChange={(e) => setEditRelatedPr(e.target.value)}
                placeholder="如 1234"
                status={editProblemCategory === '开发代码' && !editRelatedPr ? 'error' : undefined}
                style={{ marginTop: 4 }}
              />
            </div>
            <div>
              <Text type="secondary">备注：</Text>
              <TextArea value={editNotes} onChange={(e) => setEditNotes(e.target.value)}
                placeholder="输入处理备注..." rows={4} style={{ marginTop: 4 }} />
            </div>
          </Space>
        )}
      </Modal>
    </div>
  )
}

export default DailyFailureTracking
