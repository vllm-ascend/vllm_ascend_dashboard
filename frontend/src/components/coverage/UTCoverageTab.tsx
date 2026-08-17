import { useMemo, useState } from 'react'
import {
  Alert,
  Card,
  Col,
  Empty,
  Input,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useCoverageBreadth, useCoverageLines, useCoverageSyncStatus } from '../../hooks/useTestBoard'
import type { CoverageFileMatrixItem, CoverageJob } from '../../services/testBoard'

const { Text } = Typography

function coverageColor(value: number) {
  if (value >= 80) return '#52c41a'
  if (value >= 50) return '#faad14'
  return '#ff4d4f'
}

export default function UTCoverageTab() {
  const { data: breadth, isLoading: breadthLoading } = useCoverageBreadth({ per_page: 500 })
  const { data: lines, isLoading: linesLoading } = useCoverageLines({
    per_page: 500,
    sort: 'percent_covered',
    order: 'asc',
  })
  const { data: syncStatus } = useCoverageSyncStatus()
  const [search, setSearch] = useState('')
  const [hardware, setHardware] = useState<string>()

  const jobs = useMemo(() => {
    return (breadth?.jobs ?? []).filter((job) => {
      if (job.test_type !== 'ut') return false
      if (hardware && job.hardware !== hardware) return false
      if (search && !job.test_path.toLowerCase().includes(search.toLowerCase())) return false
      return true
    })
  }, [breadth?.jobs, hardware, search])

  const fileMatrix = useMemo(() => {
    return (breadth?.file_matrix ?? []).filter((file) => {
      return !search || file.source_path.toLowerCase().includes(search.toLowerCase())
    })
  }, [breadth?.file_matrix, search])

  const lineFiles = useMemo(() => {
    return (lines?.files ?? []).filter((file) => {
      return !search || file.path.toLowerCase().includes(search.toLowerCase())
    })
  }, [lines?.files, search])

  const summary = lines?.totals
  const utJobCount = breadth?.summary.by_test_type?.ut ?? jobs.length
  const status = lines?.status ?? 'unknown'

  const jobColumns = [
    { title: '测试路径', dataIndex: 'test_path', key: 'test_path', width: 360, ellipsis: true },
    { title: '硬件', dataIndex: 'hardware', key: 'hardware', width: 80, render: (value: string) => <Tag>{value}</Tag> },
    { title: '卡数', dataIndex: 'card_count', key: 'card_count', width: 70 },
    { title: '覆盖文件', dataIndex: 'source_files_covered', key: 'source_files_covered', width: 90 },
    { title: '执行次数', dataIndex: 'covdata_count', key: 'covdata_count', width: 90 },
    { title: 'arcs', dataIndex: 'arcs', key: 'arcs', width: 100, render: (value: number) => value.toLocaleString() },
    { title: '生成时间', dataIndex: 'latest_when', key: 'latest_when', width: 180, render: (value: string | null) => value || '-' },
  ]

  const fileMatrixColumns = [
    { title: '源码文件', dataIndex: 'source_path', key: 'source_path', width: 360, ellipsis: true },
    { title: '模块', dataIndex: 'module', key: 'module', width: 180, ellipsis: true },
    { title: '被覆盖作业数', dataIndex: 'covered_by_jobs', key: 'covered_by_jobs', width: 120 },
    {
      title: '覆盖硬件',
      dataIndex: 'covered_by_hardware',
      key: 'covered_by_hardware',
      width: 160,
      render: (values: string[]) => <Space size={2}>{values.map((value) => <Tag key={value}>{value}</Tag>)}</Space>,
    },
  ]

  const lineColumns = [
    { title: '文件', dataIndex: 'path', key: 'path', width: 360, ellipsis: true },
    { title: '模块', dataIndex: 'module', key: 'module', width: 180, ellipsis: true },
    { title: '语句', dataIndex: 'statements', key: 'statements', width: 80 },
    { title: '已覆盖', dataIndex: 'covered', key: 'covered', width: 80 },
    { title: '未覆盖', dataIndex: 'missing', key: 'missing', width: 80 },
    {
      title: '覆盖率',
      dataIndex: 'percent_covered',
      key: 'percent_covered',
      width: 180,
      render: (value: number) => <Progress percent={Number(value.toFixed(1))} size="small" strokeColor={coverageColor(value)} format={() => `${value.toFixed(1)}%`} />,
    },
  ]

  const moduleColumns = [
    { title: '模块', dataIndex: 'module', key: 'module', width: 220 },
    { title: '文件数', dataIndex: 'files', key: 'files', width: 80 },
    { title: '语句', dataIndex: 'statements', key: 'statements', width: 80 },
    { title: '已覆盖', dataIndex: 'covered', key: 'covered', width: 80 },
    {
      title: '覆盖率',
      dataIndex: 'percent',
      key: 'percent',
      width: 220,
      render: (value: number) => <Progress percent={Number(value.toFixed(1))} size="small" strokeColor={coverageColor(value)} format={() => `${value.toFixed(1)}%`} />,
    },
  ]

  return (
    <div>
      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search placeholder="搜索 UT 路径或源码文件" allowClear style={{ width: 300 }} onChange={(event) => setSearch(event.target.value)} />
        <Select
          placeholder="硬件"
          allowClear
          style={{ width: 120 }}
          value={hardware}
          onChange={setHardware}
          options={['A2', 'A3', '310P', 'A5'].map((value) => ({ label: value, value }))}
        />
        <Text type="secondary">
          最近同步：{syncStatus?.last_check_at ? new Date(syncStatus.last_check_at).toLocaleString() : '-'}
        </Text>
      </Space>

      {status === 'partial' && lines?.warning && (
        <Alert type="warning" showIcon message="覆盖率为近似值" description={lines.warning} style={{ marginBottom: 16 }} />
      )}
      {status === 'failed' && (
        <Alert type="error" showIcon message="UT 覆盖率同步失败" description={lines?.warning || '请先执行覆盖率同步'} style={{ marginBottom: 16 }} />
      )}

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={5}><Card loading={linesLoading}><Statistic title="UT 行覆盖率" value={summary?.percent_covered ?? 0} precision={1} suffix="%" valueStyle={{ color: coverageColor(summary?.percent_covered ?? 0) }} /></Card></Col>
        <Col span={5}><Card loading={linesLoading}><Statistic title="语句总数" value={summary?.num_statements ?? 0} /></Card></Col>
        <Col span={5}><Card loading={linesLoading}><Statistic title="已覆盖行" value={summary?.covered_lines ?? 0} valueStyle={{ color: '#3f8600' }} /></Card></Col>
        <Col span={5}><Card loading={linesLoading}><Statistic title="未覆盖行" value={summary?.missing_lines ?? 0} valueStyle={{ color: '#cf1322' }} /></Card></Col>
        <Col span={4}><Card loading={breadthLoading}><Statistic title="UT 作业" value={utJobCount} /></Card></Col>
      </Row>

      <Card title="按模块汇总" size="small" style={{ marginBottom: 16 }}>
        {lines?.by_module?.length ? <Table dataSource={lines.by_module} rowKey="module" columns={moduleColumns} size="small" pagination={false} scroll={{ x: 800 }} /> : <Empty description="暂无模块覆盖率数据" />}
      </Card>

      <Card title="UT 文件覆盖率" size="small" style={{ marginBottom: 16 }}>
        {lineFiles.length ? <Table dataSource={lineFiles} rowKey="path" columns={lineColumns} size="small" pagination={{ pageSize: 20, showTotal: (total) => `共 ${total} 个文件` }} scroll={{ x: 1000 }} /> : <Empty description="暂无 UT 行覆盖率数据" />}
      </Card>

      <Card title="UT 覆盖广度" size="small" style={{ marginBottom: 16 }}>
        {jobs.length ? <Table dataSource={jobs} rowKey={(row: CoverageJob) => `${row.job_dir}-${row.hardware}`} columns={jobColumns} size="small" pagination={{ pageSize: 15, showTotal: (total) => `共 ${total} 个作业` }} scroll={{ x: 1100 }} /> : <Empty description="暂无 UT 覆盖作业数据" />}
      </Card>

      <Card title="源码反向矩阵" size="small">
        {fileMatrix.length ? <Table dataSource={fileMatrix} rowKey={(row: CoverageFileMatrixItem) => row.source_path} columns={fileMatrixColumns} size="small" pagination={{ pageSize: 15, showTotal: (total) => `共 ${total} 个文件` }} scroll={{ x: 900 }} /> : <Empty description="暂无覆盖源码文件" />}
      </Card>
    </div>
  )
}
