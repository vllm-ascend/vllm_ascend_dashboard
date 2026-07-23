import { useState } from 'react'
import { Card, Row, Col, Statistic, Table, Input, Select, Button, Tag, Space, Progress, Typography, Empty, Alert, Tooltip, Tabs } from 'antd'
import { CodeOutlined, GithubOutlined, DownloadOutlined } from '@ant-design/icons'
import { usePRCoverageBreadth, usePRCoverageLines, useCoverageSyncStatus } from '../../hooks/useTestBoard'
import type { PRBreadthJob, PRFileMatrixItem, PRLineFile } from '../../services/testBoard'
import { heatColor, githubBlobUrl } from './coverageUtils'
import CoverageCodeViewer from './CoverageCodeViewer'

const { Text } = Typography

export default function PRCoverageTab() {
  const { data: breadth, isLoading: breadthLoading } = usePRCoverageBreadth({ per_page: 200 })
  const { data: lines, isLoading: linesLoading } = usePRCoverageLines({ per_page: 200, sort: 'percent_covered', order: 'asc' })
  const { data: syncStatus } = useCoverageSyncStatus()
  const [viewerPath, setViewerPath] = useState<string | null>(null)

  // --- 广度矩阵 ---
  const [breadthSearch, setBreadthSearch] = useState('')
  const [breadthHw, setBreadthHw] = useState<string>('')
  const jobs = breadth?.jobs ?? []
  const filteredJobs = jobs.filter((j) => {
    if (breadthSearch && !j.test_path.toLowerCase().includes(breadthSearch.toLowerCase())) return false
    if (breadthHw && j.hardware !== breadthHw) return false
    return true
  })
  const bSummary = breadth?.summary as Record<string, unknown> | undefined

  const jobColumns = [
    { title: '测试路径', dataIndex: 'test_path', key: 'test_path', width: 320, ellipsis: true,
      render: (p: string) => <Text style={{ fontSize: 12 }}>{p}</Text> },
    { title: '类型', dataIndex: 'test_type', key: 'test_type', width: 70,
      render: (t: string) => <Tag color={t === 'e2e' ? 'blue' : 'purple'}>{t}</Tag> },
    { title: '硬件', dataIndex: 'hardware', key: 'hardware', width: 80, render: (h: string) => <Tag>{h}</Tag> },
    { title: '卡数', dataIndex: 'card_count', key: 'card_count', width: 60 },
    { title: '运行次数', dataIndex: 'covdata_count', key: 'covdata_count', width: 80 },
    { title: '覆盖文件数', dataIndex: 'source_files_covered', key: 'source_files_covered', width: 90 },
    { title: 'arcs', dataIndex: 'arcs', key: 'arcs', width: 90, render: (a: number) => a?.toLocaleString() },
    { title: '时间', dataIndex: 'latest_when', key: 'latest_when', width: 160,
      render: (w: string | null) => w ? <Text type="secondary" style={{ fontSize: 12 }}>{w}</Text> : '-' },
  ]

  const fileMatrixColumns = [
    { title: '源码文件', dataIndex: 'source_path', key: 'source_path', width: 360, ellipsis: true,
      render: (p: string) => (
        <Tooltip title="在 GitHub 查看">
          <Button type="link" size="small" icon={<GithubOutlined />}
            href={githubBlobUrl(lines?.covdata_commit ?? lines?.source_commit ?? null, p)} target="_blank">
            {p}
          </Button>
        </Tooltip>
      ) },
    { title: '模块', dataIndex: 'module', key: 'module', width: 180, ellipsis: true },
    { title: '被覆盖作业数', dataIndex: 'covered_by_jobs', key: 'covered_by_jobs', width: 110, sorter: (a: PRFileMatrixItem, b: PRFileMatrixItem) => a.covered_by_jobs - b.covered_by_jobs },
    { title: '覆盖硬件', dataIndex: 'covered_by_hardware', key: 'covered_by_hardware', width: 160,
      render: (hw: string[]) => <Space size={2} wrap>{hw.map((h) => <Tag key={h}>{h}</Tag>)}</Space> },
  ]

  // --- 行覆盖率 ---
  const [lineSearch, setLineSearch] = useState('')
  const lSummary = lines?.totals
  const files = (lines?.files ?? []).filter((f) => !lineSearch || f.path.toLowerCase().includes(lineSearch.toLowerCase()))
  const status = lines?.status ?? 'unknown'

  const fileColumns = [
    { title: '文件', dataIndex: 'path', key: 'path', width: 360, ellipsis: true,
      render: (p: string) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<CodeOutlined />} onClick={() => setViewerPath(p)}>{p}</Button>
          <Tooltip title="在 GitHub 查看">
            <Button type="text" size="small" icon={<GithubOutlined />}
              href={githubBlobUrl(lines?.covdata_commit ?? lines?.source_commit ?? null, p)} target="_blank" />
          </Tooltip>
        </Space>
      ) },
    { title: '模块', dataIndex: 'module', key: 'module', width: 180, ellipsis: true },
    { title: '语句', dataIndex: 'statements', key: 'statements', width: 70 },
    { title: '未覆盖', dataIndex: 'missing', key: 'missing', width: 80, render: (m: number) => m > 0 ? <Text type="danger">{m}</Text> : m },
    { title: '覆盖率', dataIndex: 'percent_covered', key: 'percent_covered', width: 160, sorter: (a: PRLineFile, b: PRLineFile) => a.percent_covered - b.percent_covered,
      render: (p: number) => {
        const c = heatColor(p)
        return <span style={{ background: c.background, color: c.color, padding: '2px 8px', borderRadius: 4 }}>{p.toFixed(1)}%</span>
      } },
  ]

  const moduleColumns = [
    { title: '模块', dataIndex: 'module', key: 'module', width: 220 },
    { title: '语句', dataIndex: 'statements', key: 'statements', width: 80 },
    { title: '已覆盖', dataIndex: 'covered', key: 'covered', width: 80 },
    { title: '分支', dataIndex: 'branches', key: 'branches', width: 80 },
    { title: '覆盖率', dataIndex: 'percent', key: 'percent', width: 200,
      render: (p: number) => <Progress percent={Math.round(p)} size="small" strokeColor={p >= 80 ? '#52c41a' : p >= 50 ? '#faad14' : '#ff4d4f'} format={() => `${p.toFixed(1)}%`} /> },
    { title: '文件数', dataIndex: 'files', key: 'files', width: 80 },
  ]

  const syncInfo = syncStatus ? (
    <Text type="secondary" style={{ fontSize: 12 }}>
      最近检查：{syncStatus.last_check_at ? new Date(syncStatus.last_check_at).toLocaleString() : '-'}
      {syncStatus.pr_breadth && ` · 广度${syncStatus.pr_breadth.success ? '✓' : '✗'}`}
      {syncStatus.pr_lines && ` · 行覆盖${syncStatus.pr_lines.success ? '✓' : '✗'}`}
    </Text>
  ) : null

  return (
    <div>
      <div style={{ marginBottom: 12 }}>{syncInfo}</div>

      <Tabs
        items={[
          {
            key: 'breadth',
            label: '覆盖广度矩阵',
            children: (
              <div>
                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={4}><Card loading={breadthLoading}><Statistic title="测试作业" value={Number(bSummary?.total_jobs ?? 0)} /></Card></Col>
                  <Col span={4}><Card loading={breadthLoading}><Statistic title="covdata 文件" value={Number(bSummary?.total_covdata_files ?? 0)} /></Card></Col>
                  <Col span={5}><Card loading={breadthLoading}><Statistic title="覆盖源码文件" value={Number(bSummary?.total_source_files_covered ?? 0)} /></Card></Col>
                  <Col span={5}><Card loading={breadthLoading}><Statistic title="arc 总数" value={Number(bSummary?.total_arcs ?? 0)} /></Card></Col>
                  <Col span={6}><Card loading={breadthLoading}><Statistic title="生成时间" value={String(bSummary?.generated_when ?? '-')} valueStyle={{ fontSize: 14 }} /></Card></Col>
                </Row>

                <Card title="作业明细" size="small" style={{ marginBottom: 16 }}>
                  <Space wrap style={{ marginBottom: 12 }}>
                    <Input.Search placeholder="搜索测试路径" allowClear style={{ width: 260 }} onChange={(e) => setBreadthSearch(e.target.value)} />
                    <Select placeholder="硬件" allowClear style={{ width: 120 }} onChange={setBreadthHw}
                      options={['A2', 'A3', '310P'].map((h) => ({ label: h, value: h }))} />
                  </Space>
                  <Table dataSource={filteredJobs} rowKey="job_dir" columns={jobColumns} size="small"
                    pagination={{ pageSize: 15, showTotal: (t) => `共 ${t} 条` }} scroll={{ x: 1100 }} />
                </Card>

                <Card title="源码文件反向矩阵" size="small" extra={<Button size="small" icon={<DownloadOutlined />} href="/api/v1/test-board/coverage/pr-pipeline/breadth?format=csv" target="_blank">CSV</Button>}>
                  <Table dataSource={breadth?.file_matrix ?? []} rowKey="source_path" columns={fileMatrixColumns} size="small"
                    pagination={{ pageSize: 15, total: breadth?.file_matrix_total, showTotal: (t) => `共 ${t} 条` }} scroll={{ x: 900 }} />
                </Card>
              </div>
            ),
          },
          {
            key: 'lines',
            label: '行覆盖率',
            children: (
              <div>
                {status === 'partial' && lines?.warning && (
                  <Alert type="warning" showIcon style={{ marginBottom: 16 }}
                    message="近似值提示" description={lines.warning} />
                )}
                {status === 'failed' && (
                  <Alert type="error" showIcon style={{ marginBottom: 16 }}
                    message="行覆盖率同步失败" description={lines?.warning || '请稍后重试或检查后端日志'} />
                )}
                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={6}>
                    <Card loading={linesLoading}>
                      <Statistic title="总覆盖率（行+分支）"
                        value={lSummary ? lSummary.percent_covered.toFixed(1) : '0.0'} suffix="%"
                        valueStyle={{ color: (lSummary?.percent_covered ?? 0) >= 80 ? '#3f8600' : '#cf1322' }} />
                      <Progress percent={Math.round(lSummary?.percent_covered ?? 0)} size="small"
                        strokeColor={(lSummary?.percent_covered ?? 0) >= 80 ? '#52c41a' : (lSummary?.percent_covered ?? 0) >= 50 ? '#faad14' : '#ff4d4f'} />
                    </Card>
                  </Col>
                  <Col span={4}><Card loading={linesLoading}><Statistic title="语句总数" value={lSummary?.num_statements ?? 0} /></Card></Col>
                  <Col span={4}><Card loading={linesLoading}><Statistic title="已覆盖行" value={lSummary?.covered_lines ?? 0} valueStyle={{ color: '#3f8600' }} /></Card></Col>
                  <Col span={4}><Card loading={linesLoading}><Statistic title="未覆盖行" value={lSummary?.missing_lines ?? 0} valueStyle={{ color: '#cf1322' }} /></Card></Col>
                  <Col span={6}>
                    <Card loading={linesLoading} size="small">
                      <Text type="secondary" style={{ fontSize: 12 }}>行覆盖率 {lSummary?.percent_statements_covered?.toFixed(1) ?? '-'}%</Text><br />
                      <Text type="secondary" style={{ fontSize: 12 }}>分支覆盖率 {lSummary?.percent_branches_covered?.toFixed(1) ?? '-'}%</Text><br />
                      <Text type="secondary" style={{ fontSize: 12 }}>covdata {(lines?.covdata_commit || '?').slice(0, 7)}</Text>
                    </Card>
                  </Col>
                </Row>

                <Card title="按模块汇总" size="small" style={{ marginBottom: 16 }}>
                  <Table dataSource={lines?.by_module ?? []} rowKey="module" columns={moduleColumns} size="small" pagination={false} scroll={{ x: 700 }} />
                </Card>

                <Card title="文件明细" size="small" extra={<Button size="small" icon={<DownloadOutlined />} href="/api/v1/test-board/coverage/pr-pipeline/lines?format=csv" target="_blank">CSV</Button>}>
                  <Input.Search placeholder="搜索文件路径" allowClear style={{ width: 300, marginBottom: 12 }} onChange={(e) => setLineSearch(e.target.value)} />
                  {files.length ? (
                    <Table dataSource={files} rowKey="path" columns={fileColumns} size="small"
                      pagination={{ pageSize: 20, total: lines?.files_total, showTotal: (t) => `共 ${t} 条` }} scroll={{ x: 900 }} />
                  ) : <Empty description={status === 'unknown' ? '暂无行覆盖率数据（需同步方案2）' : '无匹配文件'} />}
                </Card>
              </div>
            ),
          },
        ]}
      />

      <CoverageCodeViewer path={viewerPath} commit={lines?.covdata_commit ?? lines?.source_commit ?? null} onClose={() => setViewerPath(null)} />
    </div>
  )
}
