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
  Collapse,
  Progress,
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
  CaretRightOutlined,
} from '@ant-design/icons'
import { useDailyFailures, useUpdateFailureStatus } from '../hooks/useCI'
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
  '已修复': { color: '#1677ff', icon: <CheckCircleOutlined />, label: '已修复' },
  '已关闭': { color: '#8c8c8c', icon: <CloseCircleOutlined />, label: '已关闭' },
}

const jobColumns = [
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
    title: '测试模型',
    dataIndex: 'test_model',
    key: 'test_model',
    width: 130,
    ellipsis: true,
    render: (text: string | null) => text || '-',
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
    title: '负责人',
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
    title: '耗时',
    dataIndex: 'duration_seconds',
    key: 'duration_seconds',
    width: 80,
    render: (dur: number | null) => formatDuration(dur),
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
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [workflowFilter, setWorkflowFilter] = useState<string | undefined>(undefined)
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)
  const [notesSearch, setNotesSearch] = useState<string | undefined>(undefined)
  const [editingJob, setEditingJob] = useState<DailyFailureJob | null>(null)
  const [editStatus, setEditStatus] = useState<string>('未处理')
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

  // Expose edit handler to column renderers
  ;(window as any).__openEditDailyFailure = (job: DailyFailureJob) => {
    setEditingJob(job)
    setEditStatus(job.processing_status)
    setEditNotes(job.notes || '')
  }

  const handleSaveStatus = async () => {
    if (!editingJob) return
    try {
      await updateMutation.mutateAsync({
        jobDbId: editingJob.id,
        data: { processing_status: editStatus, notes: editNotes || null },
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
            <Statistic title="已修复" value={totalStats.fixed} suffix="个" valueStyle={{ color: '#1677ff' }} />
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
              value={totalStats.total > 0 ? Math.round((totalStats.fixed + totalStats.closed) / totalStats.total * 100) : 0}
              suffix="%"
              valueStyle={{ color: totalStats.total > 0 && (totalStats.fixed + totalStats.closed) / totalStats.total >= 0.8 ? '#3f8600' : '#cf1322' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 按天分组的折叠面板 */}
      {isLoading ? (
        <Card><Text type="secondary">加载中...</Text></Card>
      ) : !data || data.length === 0 ? (
        <Card><Text type="secondary">暂无失败数据</Text></Card>
      ) : (
        <Collapse
          defaultActiveKey={data.slice(0, 3).map(d => d.date)}
          expandIcon={({ isActive }) => <CaretRightOutlined rotate={isActive ? 90 : 0} />}
          accordion={false}
        >
          {data.map((day) => {
            const dayRate = day.stats.total_failed_jobs > 0
              ? Math.round((day.stats.fixed + day.stats.closed) / day.stats.total_failed_jobs * 100)
              : 0
            return (
              <Collapse.Panel
                key={day.date}
                header={
                  <Row gutter={16} style={{ width: '100%', paddingRight: 40 }}>
                    <Col span={4}>
                      <Text strong style={{ fontSize: 15 }}>{day.date}</Text>
                      <Text type="secondary" style={{ marginLeft: 8 }}>
                        {dayjs(day.date).format('dddd')}
                      </Text>
                    </Col>
                    <Col span={2}>
                      <Statistic title="失败" value={day.stats.total_failed_jobs} suffix="个"
                        valueStyle={{ fontSize: 16, color: '#ff4d4f' }} />
                    </Col>
                    <Col span={2}>
                      <Statistic title="未处理" value={day.stats.unprocessed} suffix="个"
                        valueStyle={{ fontSize: 16, color: day.stats.unprocessed > 0 ? '#ff4d4f' : '#8c8c8c' }} />
                    </Col>
                    <Col span={2}>
                      <Statistic title="处理中" value={day.stats.processing} suffix="个"
                        valueStyle={{ fontSize: 16, color: day.stats.processing > 0 ? '#fa8c16' : '#8c8c8c' }} />
                    </Col>
                    <Col span={2}>
                      <Statistic title="已修复" value={day.stats.fixed} suffix="个"
                        valueStyle={{ fontSize: 16, color: day.stats.fixed > 0 ? '#1677ff' : '#8c8c8c' }} />
                    </Col>
                    <Col span={2}>
                      <Statistic title="已关闭" value={day.stats.closed} suffix="个"
                        valueStyle={{ fontSize: 16, color: '#8c8c8c' }} />
                    </Col>
                    <Col span={4}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>处理率</Text>
                        <Progress
                          percent={dayRate}
                          size="small"
                          status={dayRate >= 80 ? 'success' : dayRate >= 40 ? 'active' : 'exception'}
                          style={{ flex: 1, margin: 0 }}
                        />
                      </div>
                    </Col>
                  </Row>
                }
              >
                <Table
                  columns={jobColumns}
                  dataSource={day.jobs}
                  rowKey="id"
                  pagination={false}
                  scroll={{ x: 1300 }}
                  size="small"
                />
              </Collapse.Panel>
            )
          })}
        </Collapse>
      )}

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
