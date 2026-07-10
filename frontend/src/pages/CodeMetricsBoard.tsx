import { useState, useEffect, type ReactNode } from 'react'
import { Card, Tabs, Table, Statistic, Row, Col, Tag, Empty, Typography, Select, Spin, message, Button, Input, Space, Alert, Modal } from 'antd'
import { CodeOutlined, DownloadOutlined, SyncOutlined, ArrowRightOutlined, ThunderboltOutlined } from '@ant-design/icons'
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  PieChart, Pie, Cell,
} from 'recharts'
import {
  getOverview, getComplexity, getDuplication, getHeatmap, getTrends,
  getSecurity, syncHeatmap, compareVersions, exportMetrics,
  getDerivedMetrics, getAlerts, getCICorrelation, triggerCollection,
  getFileComplexity, getFileHeatmapDetail,
  type CodeMetricsOverview, type ComplexityItem, type DuplicationItem,
  type HeatmapItem, type TrendItem, type SecurityItem, type CompareResult,
  type DerivedMetrics, type CodeMetricsAlert, type CICorrelationItem,
} from '../services/codeMetrics'

const { Title, Text } = Typography

const PIE_COLORS = ['#1677ff', '#52c41a', '#faad14', '#ff4d4f', '#722ed1', '#13c2c2']

function CodeMetricsBoard() {
  const [activeTab, setActiveTab] = useState('overview')
  const [period, setPeriod] = useState(30)
  const [loading, setLoading] = useState(false)

  const [overview, setOverview] = useState<CodeMetricsOverview | null>(null)
  const [complexity, setComplexity] = useState<ComplexityItem[]>([])
  const [duplication, setDuplication] = useState<DuplicationItem[]>([])
  const [heatmap, setHeatmap] = useState<HeatmapItem[]>([])
  const [trends, setTrends] = useState<TrendItem[]>([])

  const [security, setSecurity] = useState<SecurityItem[]>([])
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null)
  const [tagA, setTagA] = useState('')
  const [tagB, setTagB] = useState('')
  const [comparing, setComparing] = useState(false)
  const [tabLoading, setTabLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)

  const [derived, setDerived] = useState<DerivedMetrics | null>(null)
  const [alerts, setAlerts] = useState<CodeMetricsAlert[]>([])
  const [ciCorrelation, setCICorrelation] = useState<CICorrelationItem[]>([])
  const [triggering, setTriggering] = useState(false)

  const [detailModal, setDetailModal] = useState<{ visible: boolean; title: string; content: ReactNode }>({ visible: false, title: '', content: null })
  const [expandedFile, setExpandedFile] = useState<string | null>(null)
  const [fileFunctions, setFileFunctions] = useState<any[]>([])

  const ensureComplexity = async () => {
    if (complexity.length === 0) {
      try { const r = await getComplexity(100); setComplexity(r.items) } catch { /* ignore */ }
    }
    return complexity
  }
  const ensureDuplication = async () => {
    if (duplication.length === 0) {
      try { const r = await getDuplication(100); setDuplication(r.items) } catch { /* ignore */ }
    }
    return duplication
  }
  const ensureSecurity = async () => {
    if (security.length === 0) {
      try { const r = await getSecurity(100); setSecurity(r.items) } catch { /* ignore */ }
    }
    return security
  }

  const loadOverview = async (d: number) => {
    setLoading(true)
    try { setOverview(await getOverview(d)) } catch (e) { console.error('Overview failed:', e); message.error('加载数据失败') }
    finally { setLoading(false) }
    getDerivedMetrics(period).then(r => setDerived(r)).catch(() => {})
  }

  useEffect(() => {
    getAlerts().then(r => setAlerts(r.alerts)).catch(() => {})
  }, [])

  useEffect(() => {
    if (activeTab === 'overview') loadOverview(period)
    else if (activeTab === 'complexity') {
      setTabLoading(true)
      getComplexity(100).then(r => setComplexity(r.items)).catch(e => { console.error(e); message.error('加载数据失败') }).finally(() => setTabLoading(false))
    }
    else if (activeTab === 'duplication') {
      setTabLoading(true)
      getDuplication(100).then(r => setDuplication(r.items)).catch(e => { console.error(e); message.error('加载数据失败') }).finally(() => setTabLoading(false))
    }
    else if (activeTab === 'heatmap') {
      setTabLoading(true)
      getHeatmap(50).then(r => setHeatmap(r.items)).catch(e => { console.error(e); message.error('加载数据失败') }).finally(() => setTabLoading(false))
    }
    else if (activeTab === 'trends') {
      setTabLoading(true)
      getTrends(period).then(r => setTrends(r.items)).catch(e => { console.error(e); message.error('加载数据失败') }).finally(() => setTabLoading(false))
    }
    else if (activeTab === 'security') {
      setTabLoading(true)
      getSecurity(100).then(r => setSecurity(r.items)).catch(e => { console.error(e); message.error('加载失败') }).finally(() => setTabLoading(false))
    }
    else if (activeTab === 'compare') {
      // no auto-load, wait for user input
    }
    else if (activeTab === 'ci-correlation') {
      setTabLoading(true)
      getCICorrelation(period).then(r => setCICorrelation(r.items)).catch(e => { console.error(e); message.error('加载失败') }).finally(() => setTabLoading(false))
    }
  }, [activeTab, period])

  const radarData = overview?.health_scores ? [
    { dimension: '复杂度', score: overview.health_scores.complexity || 0 },
    { dimension: '安全', score: overview.health_scores.security || 0 },
    { dimension: '重复率', score: overview.health_scores.duplication || 0 },
    { dimension: '函数体量', score: overview.health_scores.method_size || 0 },
    { dimension: '技术债务', score: overview.health_scores.tech_debt || 0 },
    { dimension: 'Lint', score: overview.health_scores.lint || 0 },
  ] : []

  const languagePieData = overview?.language_loc
    ? Object.entries(overview.language_loc).map(([name, value]) => ({ name, value }))
    : []

  const modulePieData = overview?.module_loc
    ? Object.entries(overview.module_loc).map(([name, value]) => ({ name, value }))
    : []

  const tabItems = [
    {
      key: 'overview',
      label: '总览',
      children: (
        <Spin spinning={loading}>
          {!overview?.has_data ? (
            <Empty description="暂无代码度量数据，请等待 CI 采集" />
          ) : (
            <>
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={4}><Card><Statistic title="健康度评分" value={overview.health_score || 0} suffix="/100" valueStyle={{ color: (overview.health_score || 0) >= 80 ? '#52c41a' : (overview.health_score || 0) >= 60 ? '#faad14' : '#ff4d4f' }} /></Card></Col>
                <Col span={4}><Card><Statistic title="代码行数" value={overview.metrics?.total_loc || 0} /></Card></Col>
                <Col span={4}><Card><Statistic title="函数总数" value={overview.metrics?.total_functions || 0} /></Card></Col>
                <Col span={4}><Card><Statistic title="文件总数" value={overview.metrics?.total_files || 0} /></Card></Col>
                <Col span={4}>
                  <Card hoverable onClick={async () => {
                    const items = await ensureComplexity()
                    setDetailModal({
                      visible: true,
                      title: '超大复杂度函数列表',
                      content: (
                        <Table
                          dataSource={items}
                          rowKey={(r) => `${r.file_path}:${r.function_name}`}
                          columns={[
                            { title: '函数', dataIndex: 'function_name', width: 200 },
                            { title: '文件', dataIndex: 'file_path', ellipsis: true },
                            { title: '复杂度', dataIndex: 'cyclomatic_complexity', width: 80, render: (v: number) => <Tag color={(v || 0) > 20 ? 'red' : 'orange'}>{v}</Tag> },
                          ]}
                          pagination={{ pageSize: 10 }}
                        />
                      ),
                    })
                  }}>
                    <Statistic title="超大复杂度函数" value={overview.metrics?.cc_huge_count || 0} valueStyle={{ color: (overview.metrics?.cc_huge_count || 0) > 0 ? '#ff4d4f' : '#52c41a' }} />
                  </Card>
                </Col>
                <Col span={4}>
                  <Card hoverable onClick={async () => {
                    const items = await ensureDuplication()
                    setDetailModal({
                      visible: true,
                      title: '重复代码块列表',
                      content: (
                        <Table
                          dataSource={items}
                          rowKey={(r) => `${r.file_a}:${r.file_b}`}
                          columns={[
                            { title: '文件 A', dataIndex: 'file_a', ellipsis: true },
                            { title: '文件 B', dataIndex: 'file_b', ellipsis: true },
                            { title: '重复行数', dataIndex: 'lines', width: 100 },
                            { title: '代码片段', dataIndex: 'fragment', ellipsis: true, width: 300 },
                          ]}
                          pagination={{ pageSize: 10 }}
                        />
                      ),
                    })
                  }}>
                    <Statistic title="重复率" value={overview.metrics?.dup_ratio || 0} precision={2} suffix="%" valueStyle={{ color: (overview.metrics?.dup_ratio || 0) > 10 ? '#ff4d4f' : '#52c41a' }} />
                  </Card>
                </Col>
              </Row>

              <Row gutter={16}>
                <Col span={12}>
                  <Card title="健康度雷达图" size="small">
                    <ResponsiveContainer width="100%" height={300}>
                      <RadarChart data={radarData}>
                        <PolarGrid />
                        <PolarAngleAxis dataKey="dimension" />
                        <PolarRadiusAxis domain={[0, 100]} />
                        <Radar name="评分" dataKey="score" stroke="#1677ff" fill="#1677ff" fillOpacity={0.6} />
                      </RadarChart>
                    </ResponsiveContainer>
                  </Card>
                </Col>
                <Col span={6}>
                  <Card title="语言分布" size="small">
                    <ResponsiveContainer width="100%" height={300}>
                      <PieChart>
                        <Pie data={languagePieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label={(e: any) => e.name}>
                          {languagePieData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                        </Pie>
                        <Tooltip />
                      </PieChart>
                    </ResponsiveContainer>
                  </Card>
                </Col>
                <Col span={6}>
                  <Card title="模块分布" size="small">
                    <ResponsiveContainer width="100%" height={300}>
                      <PieChart>
                        <Pie data={modulePieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label={(e: any) => e.name}>
                          {modulePieData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                        </Pie>
                        <Tooltip />
                      </PieChart>
                    </ResponsiveContainer>
                  </Card>
                </Col>
              </Row>

              <Card title="更多指标" size="small" style={{ marginTop: 16 }}>
                <Row gutter={16}>
                  <Col span={4}><Statistic title="平均复杂度" value={overview.metrics?.cc_per_method || 0} precision={1} /></Col>
                  <Col span={4}><Statistic title="最大复杂度" value={overview.metrics?.cc_maximum || 0} /></Col>
                  <Col span={4}><Statistic title="重复块数" value={overview.metrics?.dup_blocks || 0} /></Col>
                  <Col span={4}>
                    <div style={{ cursor: 'pointer' }} onClick={async () => {
                      const items = await ensureSecurity()
                      setDetailModal({
                        visible: true,
                        title: '不安全函数列表',
                        content: (
                          <Table
                            dataSource={items}
                            rowKey={(r, i) => String(i)}
                            columns={[
                              { title: '严重级别', dataIndex: 'severity', width: 100, render: (v: string) => <Tag color={v === 'error' ? 'red' : v === 'warning' ? 'orange' : 'blue'}>{v || '-'}</Tag> },
                              { title: '工具', dataIndex: 'tool', width: 100 },
                              { title: '规则', dataIndex: 'rule_id', width: 150 },
                              { title: '文件', dataIndex: 'file_path', ellipsis: true },
                              { title: '行号', dataIndex: 'line_number', width: 80 },
                              { title: '消息', dataIndex: 'message', ellipsis: true },
                            ]}
                            pagination={{ pageSize: 10 }}
                          />
                        ),
                      })
                    }}>
                      <Statistic title="不安全函数" value={overview.metrics?.unsafe_functions_count || 0} valueStyle={{ color: (overview.metrics?.unsafe_functions_count || 0) > 0 ? '#ff4d4f' : '#52c41a' }} />
                    </div>
                  </Col>
                  <Col span={4}><Statistic title="Lint 错误" value={overview.metrics?.lint_errors || 0} /></Col>
                  <Col span={4}>
                    <div style={{ cursor: 'pointer' }} onClick={() => {
                      setDetailModal({
                        visible: true,
                        title: 'TODO / FIXME 统计',
                        content: (
                          <Row gutter={16}>
                            <Col span={12}><Statistic title="TODO" value={overview.metrics?.todo_count || 0} /></Col>
                            <Col span={12}><Statistic title="FIXME" value={overview.metrics?.fixme_count || 0} /></Col>
                          </Row>
                        ),
                      })
                    }}>
                      <Statistic title="TODO/FIXME" value={(overview.metrics?.todo_count || 0) + (overview.metrics?.fixme_count || 0)} />
                    </div>
                  </Col>
                </Row>
                <Row gutter={16} style={{ marginTop: 16 }}>
                  <Col span={6}><Statistic title="TODO" value={overview.metrics?.todo_count || 0} /></Col>
                  <Col span={6}><Statistic title="FIXME" value={overview.metrics?.fixme_count || 0} /></Col>
                  <Col span={6}><Statistic title="不安全函数" value={overview.metrics?.unsafe_functions_count || 0} valueStyle={{ color: (overview.metrics?.unsafe_functions_count || 0) > 0 ? '#ff4d4f' : '#52c41a' }} /></Col>
                  <Col span={6}><Statistic title="Lint 错误" value={overview.metrics?.lint_errors || 0} /></Col>
                </Row>
              </Card>

              {derived && (
                <Card title="PR 衍生指标" size="small" style={{ marginTop: 16 }}>
                  <Row gutter={16}>
                    <Col span={4}><Statistic title="PR 总数" value={derived.pr_count} /></Col>
                    <Col span={4}><Statistic title="新增行数" value={derived.total_additions} /></Col>
                    <Col span={4}><Statistic title="删除行数" value={derived.total_deletions} /></Col>
                  </Row>
                  <Row gutter={16} style={{ marginTop: 16 }}>
                    <Col span={12}>
                      <Text strong>PR 大小分布</Text>
                      <div style={{ marginTop: 8 }}>
                        {Object.entries(derived.size_distribution).map(([k, v]) => (
                          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                            <Text>{k}</Text>
                            <Tag>{v}</Tag>
                          </div>
                        ))}
                      </div>
                    </Col>
                    <Col span={12}>
                      <Text strong>修改类型分布</Text>
                      <div style={{ marginTop: 8 }}>
                        {Object.entries(derived.type_distribution).map(([k, v]) => (
                          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                            <Text>{k}</Text>
                            <Tag>{v}</Tag>
                          </div>
                        ))}
                      </div>
                    </Col>
                  </Row>
                </Card>
              )}

              <div style={{ marginTop: 8, textAlign: 'right' }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  快照日期: {overview.snapshot_date} | 状态: {overview.collection_status}
                </Text>
              </div>
            </>
          )}
        </Spin>
      ),
    },
    {
      key: 'complexity',
      label: '复杂度',
      children: (
        <Spin spinning={tabLoading}>
          <Table
            dataSource={complexity}
            rowKey={(r) => `${r.file_path}:${r.function_name}`}
            expandable={{
              expandedRowKeys: expandedFile ? [expandedFile] : [],
              onExpand: async (expanded: boolean, record: ComplexityItem) => {
                if (expanded) {
                  setExpandedFile(`${record.file_path}:${record.function_name}`)
                  try {
                    const r = await getFileComplexity(record.file_path)
                    setFileFunctions(r.items)
                  } catch { setFileFunctions([]) }
                } else {
                  setExpandedFile(null)
                }
              },
              expandedRowRender: () => (
                <Table
                  dataSource={fileFunctions}
                  rowKey="function_name"
                  size="small"
                  columns={[
                    { title: '函数', dataIndex: 'function_name', width: 250 },
                    { title: '复杂度', dataIndex: 'cyclomatic_complexity', width: 80 },
                    { title: '嵌套深度', dataIndex: 'max_nesting_depth', width: 80 },
                    { title: '行数', dataIndex: 'function_lines', width: 80 },
                    { title: '起始行', dataIndex: 'start_line', width: 80 },
                  ]}
                  pagination={false}
                />
              ),
            }}
            columns={[
              { title: '函数', dataIndex: 'function_name', width: 200 },
              { title: '文件', dataIndex: 'file_path', width: 300, ellipsis: true },
              { title: '语言', dataIndex: 'language', width: 80, render: (v: string) => v ? <Tag color={v === 'Python' ? 'blue' : 'orange'}>{v}</Tag> : '-' },
              { title: '圈复杂度', dataIndex: 'cyclomatic_complexity', width: 100, sorter: (a: ComplexityItem, b: ComplexityItem) => (a.cyclomatic_complexity || 0) - (b.cyclomatic_complexity || 0), render: (v: number) => <Tag color={(v || 0) > 20 ? 'red' : (v || 0) > 15 ? 'orange' : 'green'}>{v}</Tag> },
              { title: '嵌套深度', dataIndex: 'max_nesting_depth', width: 100 },
              { title: '函数行数', dataIndex: 'function_lines', width: 100 },
            ]}
            pagination={{ pageSize: 20 }}
          />
        </Spin>
      ),
    },
    {
      key: 'duplication',
      label: '重复率',
      children: (
        <Spin spinning={tabLoading}>
          <Table
            dataSource={duplication}
            rowKey={(r) => `${r.file_a}:${r.file_b}`}
            columns={[
              { title: '文件 A', dataIndex: 'file_a', ellipsis: true },
              { title: '文件 B', dataIndex: 'file_b', ellipsis: true },
              { title: '重复行数', dataIndex: 'lines', width: 100, sorter: (a: DuplicationItem, b: DuplicationItem) => a.lines - b.lines },
              { title: '代码片段', dataIndex: 'fragment', ellipsis: true, width: 300 },
            ]}
            pagination={{ pageSize: 20 }}
          />
        </Spin>
      ),
    },
    {
      key: 'security',
      label: '安全规范',
      children: (
        <Spin spinning={tabLoading}>
          <Table
            dataSource={security}
            rowKey={(r, i) => String(i)}
            columns={[
              { title: '严重级别', dataIndex: 'severity', width: 100, render: (v: string) => <Tag color={v === 'error' ? 'red' : v === 'warning' ? 'orange' : 'blue'}>{v || '-'}</Tag> },
              { title: '工具', dataIndex: 'tool', width: 100 },
              { title: '规则', dataIndex: 'rule_id', width: 150 },
              { title: '文件', dataIndex: 'file_path', ellipsis: true },
              { title: '行号', dataIndex: 'line_number', width: 80 },
              { title: '消息', dataIndex: 'message', ellipsis: true },
            ]}
            pagination={{ pageSize: 20 }}
          />
        </Spin>
      ),
    },
    {
      key: 'heatmap',
      label: '热力图',
      children: (
        <Spin spinning={tabLoading}>
          <Button icon={<SyncOutlined />} loading={syncing} onClick={async () => {
            setSyncing(true)
            try {
              const r = await syncHeatmap(30)
              message.success(`同步完成: ${r.updated} 个文件`)
              const h = await getHeatmap(50)
              setHeatmap(h.items)
            } catch { message.error('同步失败') }
            finally { setSyncing(false) }
          }} style={{ marginBottom: 16 }}>从 PR 数据同步热力图</Button>
          <Table
            dataSource={heatmap}
            rowKey="file_path"
            columns={[
              { title: '文件路径', dataIndex: 'file_path', ellipsis: true },
              { title: '变更次数', dataIndex: 'change_count', width: 100, sorter: (a: HeatmapItem, b: HeatmapItem) => a.change_count - b.change_count, render: (v: number) => <Tag color={v > 20 ? 'red' : v > 10 ? 'orange' : 'blue'}>{v}</Tag> },
              { title: 'Bug 修复次数', dataIndex: 'bug_fix_count', width: 120 },
              { title: '最后变更', dataIndex: 'last_changed', width: 180 },
            ]}
            onRow={(record: HeatmapItem) => ({
              onClick: async () => {
                try {
                  const detail = await getFileHeatmapDetail(record.file_path)
                  setDetailModal({
                    visible: true,
                    title: `文件变更详情: ${record.file_path}`,
                    content: (
                      <div>
                        <Row gutter={16}>
                          <Col span={8}><Statistic title="变更次数" value={detail.change_count || 0} /></Col>
                          <Col span={8}><Statistic title="Bug修复次数" value={detail.bug_fix_count || 0} /></Col>
                          <Col span={8}><Statistic title="最后变更" value={detail.last_changed || 'N/A'} /></Col>
                        </Row>
                      </div>
                    ),
                  })
                } catch { message.error('加载详情失败') }
              }
            })}
            pagination={{ pageSize: 20 }}
          />
        </Spin>
      ),
    },
    {
      key: 'trends',
      label: '趋势',
      children: (
        <Spin spinning={tabLoading}>
          <Select value={period} onChange={setPeriod} options={[
            { label: '近 30 天', value: 30 },
            { label: '近 90 天', value: 90 },
            { label: '近 180 天', value: 180 },
            { label: '近 365 天', value: 365 },
          ]} style={{ marginBottom: 16 }} />
          <Card title="代码规模趋势" size="small" style={{ marginBottom: 16 }}>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={trends} onClick={(e: any) => {
                if (e && e.activePayload && e.activePayload[0]) {
                  const data = e.activePayload[0].payload
                  setDetailModal({
                    visible: true,
                    title: `快照详情: ${data.date}`,
                    content: (
                      <Row gutter={16}>
                        <Col span={6}><Statistic title="代码行数" value={data.total_loc} /></Col>
                        <Col span={6}><Statistic title="函数总数" value={data.total_functions} /></Col>
                        <Col span={6}><Statistic title="健康度" value={data.health_score} /></Col>
                        <Col span={6}><Statistic title="超大复杂度" value={data.cc_huge_count} /></Col>
                        <Col span={6}><Statistic title="重复率" value={data.dup_ratio} suffix="%" /></Col>
                        <Col span={6}><Statistic title="Lint错误" value={data.lint_errors} /></Col>
                        <Col span={6}><Statistic title="TODO/FIXME" value={data.todo_count} /></Col>
                      </Row>
                    ),
                  })
                }
              }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="total_loc" name="代码行数" stroke="#1677ff" />
                <Line type="monotone" dataKey="total_functions" name="函数总数" stroke="#52c41a" />
              </LineChart>
            </ResponsiveContainer>
          </Card>
          <Card title="质量趋势" size="small">
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={trends} onClick={(e: any) => {
                if (e && e.activePayload && e.activePayload[0]) {
                  const data = e.activePayload[0].payload
                  setDetailModal({
                    visible: true,
                    title: `快照详情: ${data.date}`,
                    content: (
                      <Row gutter={16}>
                        <Col span={6}><Statistic title="代码行数" value={data.total_loc} /></Col>
                        <Col span={6}><Statistic title="函数总数" value={data.total_functions} /></Col>
                        <Col span={6}><Statistic title="健康度" value={data.health_score} /></Col>
                        <Col span={6}><Statistic title="超大复杂度" value={data.cc_huge_count} /></Col>
                        <Col span={6}><Statistic title="重复率" value={data.dup_ratio} suffix="%" /></Col>
                        <Col span={6}><Statistic title="Lint错误" value={data.lint_errors} /></Col>
                        <Col span={6}><Statistic title="TODO/FIXME" value={data.todo_count} /></Col>
                      </Row>
                    ),
                  })
                }
              }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="health_score" name="健康度" stroke="#1677ff" />
                <Line type="monotone" dataKey="cc_per_method" name="平均复杂度" stroke="#faad14" />
                <Line type="monotone" dataKey="dup_ratio" name="重复率" stroke="#ff4d4f" />
              </LineChart>
            </ResponsiveContainer>
          </Card>
        </Spin>
      ),
    },
    {
      key: 'compare',
      label: '版本对比',
      children: (
        <>
          <Space style={{ marginBottom: 16 }}>
            <Input placeholder="Tag A (如 v0.13.0)" value={tagA} onChange={e => setTagA(e.target.value)} style={{ width: 200 }} />
            <ArrowRightOutlined />
            <Input placeholder="Tag B (如 v0.18.0)" value={tagB} onChange={e => setTagB(e.target.value)} style={{ width: 200 }} />
            <Button type="primary" loading={comparing} disabled={!tagA || !tagB} onClick={async () => {
              setComparing(true)
              try {
                const result = await compareVersions(tagA, tagB)
                setCompareResult(result)
                if (result.error) message.warning(result.error)
              } catch (e) { message.error('对比失败') }
              finally { setComparing(false) }
            }}>对比</Button>
          </Space>
          {compareResult?.a && compareResult?.b ? (
            <Table
              dataSource={Object.keys(compareResult.a).filter(k => k !== 'tag' && k !== 'snapshot_date').map(k => ({
                key: k, metric: k, a: compareResult.a![k], b: compareResult.b![k], delta: compareResult.deltas[k] || 0
              }))}
              columns={[
                { title: '指标', dataIndex: 'metric', width: 200 },
                { title: compareResult.a.tag || 'A', dataIndex: 'a', width: 150 },
                { title: compareResult.b.tag || 'B', dataIndex: 'b', width: 150 },
                { title: '变化', dataIndex: 'delta', width: 100, render: (v: number) => <Tag color={v > 0 ? 'red' : v < 0 ? 'green' : 'default'}>{v > 0 ? '+' : ''}{v}</Tag> },
              ]}
              pagination={false}
            />
          ) : compareResult?.error ? (
            <Empty description={compareResult.error} />
          ) : (
            <Empty description="输入两个 tag 进行对比" />
          )}
        </>
      ),
    },
    {
      key: 'ci-correlation',
      label: 'CI 关联',
      children: (
        <Spin spinning={tabLoading}>
          {ciCorrelation.length === 0 ? (
            <Empty description="暂无关联数据" />
          ) : (
            <>
              <Card title="代码质量 vs CI 成功率" size="small" style={{ marginBottom: 16 }}>
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={ciCorrelation}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" />
                    <YAxis yAxisId="left" />
                    <YAxis yAxisId="right" orientation="right" />
                    <Tooltip />
                    <Legend />
                    <Line yAxisId="left" type="monotone" dataKey="health_score" name="健康度" stroke="#1677ff" />
                    <Line yAxisId="right" type="monotone" dataKey="ci_success_rate" name="CI 成功率(%)" stroke="#52c41a" />
                  </LineChart>
                </ResponsiveContainer>
              </Card>
              <Card title="超大复杂度函数 vs CI 成功率" size="small">
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={ciCorrelation}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" />
                    <YAxis yAxisId="left" />
                    <YAxis yAxisId="right" orientation="right" />
                    <Tooltip />
                    <Legend />
                    <Line yAxisId="left" type="monotone" dataKey="cc_huge_count" name="超大复杂度函数数" stroke="#ff4d4f" />
                    <Line yAxisId="right" type="monotone" dataKey="ci_success_rate" name="CI 成功率(%)" stroke="#52c41a" />
                  </LineChart>
                </ResponsiveContainer>
              </Card>
            </>
          )}
        </Spin>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            <CodeOutlined style={{ marginRight: 8 }} />
            代码度量看板
          </Title>
          <Text type="secondary">vllm-ascend 仓库代码质量量化度量 — 圈复杂度 / 重复率 / 安全规范</Text>
        </div>
        <Space>
          <Button icon={<ThunderboltOutlined />} loading={triggering} onClick={async () => {
            setTriggering(true)
            try {
              const r = await triggerCollection('main')
              if (r.status === 'triggered') message.success('采集任务已触发')
              else message.warning(r.message || '触发失败')
            } catch { message.error('触发失败') }
            finally { setTriggering(false) }
          }}>手动采集</Button>
          <Button icon={<DownloadOutlined />} onClick={async () => {
            try {
              const blob = await exportMetrics('csv', period)
              const url = URL.createObjectURL(blob)
              const a = document.createElement('a')
              a.href = url
              a.download = 'code_metrics.csv'
              a.click()
              URL.revokeObjectURL(url)
              message.success('导出成功')
            } catch { message.error('导出失败') }
          }}>导出 CSV</Button>
        </Space>
      </div>
      {alerts.length > 0 && (
        <Alert
          message={`代码度量告警 (${alerts.length})`}
          description={
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {alerts.map((a, i) => (
                <li key={i}>
                  <Tag color={a.level === 'error' ? 'red' : a.level === 'warning' ? 'orange' : 'blue'}>{a.level}</Tag>
                  {a.message}
                </li>
              ))}
            </ul>
          }
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
      <Modal
        open={detailModal.visible}
        title={detailModal.title}
        onCancel={() => setDetailModal({ ...detailModal, visible: false })}
        footer={null}
        width={800}
      >
        {detailModal.content}
      </Modal>
    </div>
  )
}

export default CodeMetricsBoard
