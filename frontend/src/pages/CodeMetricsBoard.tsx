import { useState, useEffect } from 'react'
import { Card, Tabs, Table, Statistic, Row, Col, Tag, Empty, Typography, Select, Spin } from 'antd'
import { CodeOutlined } from '@ant-design/icons'
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  PieChart, Pie, Cell,
} from 'recharts'
import {
  getOverview, getComplexity, getDuplication, getHeatmap, getTrends,
  type CodeMetricsOverview, type ComplexityItem, type DuplicationItem,
  type HeatmapItem, type TrendItem,
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

  const loadOverview = async (d: number) => {
    setLoading(true)
    try { setOverview(await getOverview(d)) } catch (e) { console.error('Overview failed:', e) }
    finally { setLoading(false) }
  }

  useEffect(() => {
    if (activeTab === 'overview') loadOverview(period)
    else if (activeTab === 'complexity') getComplexity(100).then(r => setComplexity(r.items)).catch(e => console.error(e))
    else if (activeTab === 'duplication') getDuplication(100).then(r => setDuplication(r.items)).catch(e => console.error(e))
    else if (activeTab === 'heatmap') getHeatmap(50).then(r => setHeatmap(r.items)).catch(e => console.error(e))
    else if (activeTab === 'trends') getTrends(period).then(r => setTrends(r.items)).catch(e => console.error(e))
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
                <Col span={4}><Card><Statistic title="超大复杂度函数" value={overview.metrics?.cc_huge_count || 0} valueStyle={{ color: (overview.metrics?.cc_huge_count || 0) > 0 ? '#ff4d4f' : '#52c41a' }} /></Card></Col>
                <Col span={4}><Card><Statistic title="重复率" value={overview.metrics?.dup_ratio || 0} precision={2} suffix="%" valueStyle={{ color: (overview.metrics?.dup_ratio || 0) > 10 ? '#ff4d4f' : '#52c41a' }} /></Card></Col>
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
                  <Col span={4}><Statistic title="不安全函数" value={overview.metrics?.unsafe_functions_count || 0} valueStyle={{ color: (overview.metrics?.unsafe_functions_count || 0) > 0 ? '#ff4d4f' : '#52c41a' }} /></Col>
                  <Col span={4}><Statistic title="Lint 错误" value={overview.metrics?.lint_errors || 0} /></Col>
                  <Col span={4}><Statistic title="TODO/FIXME" value={(overview.metrics?.todo_count || 0) + (overview.metrics?.fixme_count || 0)} /></Col>
                </Row>
              </Card>

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
        <Table
          dataSource={complexity}
          rowKey={(r) => `${r.file_path}:${r.function_name}`}
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
      ),
    },
    {
      key: 'duplication',
      label: '重复率',
      children: (
        <Table
          dataSource={duplication}
          rowKey={(r, i) => String(i)}
          columns={[
            { title: '文件 A', dataIndex: 'file_a', ellipsis: true },
            { title: '文件 B', dataIndex: 'file_b', ellipsis: true },
            { title: '重复行数', dataIndex: 'lines', width: 100, sorter: (a: DuplicationItem, b: DuplicationItem) => a.lines - b.lines },
            { title: '代码片段', dataIndex: 'fragment', ellipsis: true, width: 300 },
          ]}
          pagination={{ pageSize: 20 }}
        />
      ),
    },
    {
      key: 'heatmap',
      label: '热力图',
      children: (
        <Table
          dataSource={heatmap}
          rowKey="file_path"
          columns={[
            { title: '文件路径', dataIndex: 'file_path', ellipsis: true },
            { title: '变更次数', dataIndex: 'change_count', width: 100, sorter: (a: HeatmapItem, b: HeatmapItem) => a.change_count - b.change_count, render: (v: number) => <Tag color={v > 20 ? 'red' : v > 10 ? 'orange' : 'blue'}>{v}</Tag> },
            { title: 'Bug 修复次数', dataIndex: 'bug_fix_count', width: 120 },
            { title: '最后变更', dataIndex: 'last_changed', width: 180 },
          ]}
          pagination={{ pageSize: 20 }}
        />
      ),
    },
    {
      key: 'trends',
      label: '趋势',
      children: (
        <>
          <Select value={period} onChange={setPeriod} options={[
            { label: '近 30 天', value: 30 },
            { label: '近 90 天', value: 90 },
            { label: '近 180 天', value: 180 },
            { label: '近 365 天', value: 365 },
          ]} style={{ marginBottom: 16 }} />
          <Card title="代码规模趋势" size="small" style={{ marginBottom: 16 }}>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={trends}>
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
              <LineChart data={trends}>
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
        </>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>
          <CodeOutlined style={{ marginRight: 8 }} />
          代码度量看板
        </Title>
        <Text type="secondary">vllm-ascend 仓库代码质量量化度量 — 圈复杂度 / 重复率 / 安全规范</Text>
      </div>
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
    </div>
  )
}

export default CodeMetricsBoard
