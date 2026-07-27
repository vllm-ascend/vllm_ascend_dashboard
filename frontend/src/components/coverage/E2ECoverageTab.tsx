import { useState, useMemo } from 'react'
import { Card, Row, Col, Statistic, Table, Input, Select, Checkbox, Button, Tag, Space, Progress, Typography, Empty, Tooltip } from 'antd'
import { DownloadOutlined, GithubOutlined } from '@ant-design/icons'
import { useE2ECoverage } from '../../hooks/useTestBoard'
import type { E2ETestItem } from '../../services/testBoard'
import { githubBlobUrl, e2eFullRepoPath } from './coverageUtils'

const { Text } = Typography

const TAG_COLORS: Record<string, string> = {
  arch: 'blue', feature: 'magenta', parallel: 'green', deploy: 'gold',
  hardware: 'purple', quantization: 'red', graph_mode: 'cyan',
}
const DIM_LABEL: Record<string, string> = {
  arch: '架构', feature: '特性', parallel: '并行', deploy: '部署',
  hardware: '硬件', quantization: '量化', graph_mode: '图模式',
}
const DIM_ORDER = ['arch', 'feature', 'parallel', 'deploy', 'hardware', 'quantization', 'graph_mode'] as const
type DimKey = typeof DIM_ORDER[number]

const PRESETS: Record<string, DimKey[]> = {
  'arch × quant × graph': ['arch', 'quantization', 'graph_mode'],
  'arch × feature × hw': ['arch', 'feature', 'hardware'],
  'feature × parallel × graph': ['feature', 'parallel', 'graph_mode'],
  '全部维度': [...DIM_ORDER],
}

interface ComboRow {
  key: string
  combo: string[]
  count: number
  tests: E2ETestItem[]
}

function computeCoveredCombos(tests: E2ETestItem[], dims: DimKey[]): ComboRow[] {
  if (dims.length === 0) return []
  const map = new Map<string, ComboRow>()
  for (const t of tests) {
    const sets = dims.map((d) => {
      const vals = t.coverage[d]
      return vals && vals.length ? vals : []
    })
    if (sets.some((s) => s.length === 0)) continue
    let combos: string[][] = [[]]
    for (const s of sets) {
      const next: string[][] = []
      for (const c of combos) for (const v of s) next.push([...c, v])
      combos = next
    }
    for (const combo of combos) {
      const key = combo.join('\x01')
      let entry = map.get(key)
      if (!entry) { entry = { key, combo, count: 0, tests: [] }; map.set(key, entry) }
      entry.count++
      entry.tests.push(t)
    }
  }
  return [...map.values()].sort((a, b) => b.count - a.count)
}

function tags(vals: string[] | undefined, dim: string) {
  if (!vals || vals.length === 0) return <Text type="secondary">-</Text>
  return <Space size={2} wrap>{vals.map((v) => <Tag key={v} color={TAG_COLORS[dim]}>{v}</Tag>)}</Space>
}

export default function E2ECoverageTab() {
  const { data, isLoading } = useE2ECoverage()
  const [search, setSearch] = useState('')
  const [card, setCard] = useState<string>('')
  const [arch, setArch] = useState<string>('')
  const [graph, setGraph] = useState<string>('')
  const [showUnmarked, setShowUnmarked] = useState(false)

  const tests = data?.tests ?? []
  const filtered = useMemo(() => {
    let r = tests
    if (search) {
      const s = search.toLowerCase()
      r = r.filter((t) =>
        t.filepath.toLowerCase().includes(s) ||
        t.test_name.toLowerCase().includes(s) ||
        t.models.some((m) => m.toLowerCase().includes(s)) ||
        Object.values(t.coverage).flat().some((v) => v.toLowerCase().includes(s)),
      )
    }
    if (card) r = r.filter((t) => String(t.card_count) === card)
    if (arch) r = r.filter((t) => t.coverage.arch?.includes(arch))
    if (graph) r = r.filter((t) => t.coverage.graph_mode?.includes(graph))
    if (!showUnmarked) r = r.filter((t) => t.is_marked)
    return r
  }, [tests, search, card, arch, graph, showUnmarked])

  const summary = data?.summary
  const repoCommit = data?.repo_commit ?? null
  const archOpts = (data?.taxonomy?.arch ?? []).map((v) => ({ label: v, value: v }))
  const graphOpts = (data?.taxonomy?.graph_mode ?? []).map((v) => ({ label: v, value: v }))

  const exportCSV = () => {
    const dims = ['arch', 'feature', 'parallel', 'deploy', 'hardware', 'quantization', 'graph_mode']
    const header = ['File', 'Test', 'Card', 'Models', ...dims]
    const dataToExport = comboFilter ? explorerFiltered : filtered
    const rows = dataToExport.map((t) => [
      t.filepath, t.test_name, t.card_count, t.models.join(';'),
      ...dims.map((d) => (t.coverage[d] || []).join(';')),
    ])
    const csv = [header, ...rows].map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'e2e_coverage.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  const columns = [
    {
      title: '文件', dataIndex: 'filepath', key: 'filepath', width: 260, ellipsis: true,
      render: (fp: string) => (
        <Tooltip title="在 GitHub 查看">
          <Button type="link" size="small" icon={<GithubOutlined />} href={githubBlobUrl(repoCommit, e2eFullRepoPath(fp))} target="_blank">
            {fp}
          </Button>
        </Tooltip>
      ),
    },
    { title: '测试', dataIndex: 'test_name', key: 'test_name', width: 240, ellipsis: true },
    {
      title: 'Models', dataIndex: 'models', key: 'models', width: 160,
      render: (m: string[]) => m.length ? <Space size={2} wrap>{m.map((x) => <Tag key={x} color="green">{x}</Tag>)}</Space> : <Text type="secondary">-</Text>,
    },
    ...(DIM_ORDER as readonly DimKey[]).map((dim) => ({
      title: DIM_LABEL[dim], key: dim, width: 120,
      render: (_: unknown, r: E2ETestItem) => tags(r.coverage[dim], dim),
    })),
  ]

  const grouped = [1, 2, 4].map((c) => ({ card: c, items: filtered.filter((t) => t.card_count === c) })).filter((g) => g.items.length)

  const [explorerDims, setExplorerDims] = useState<DimKey[]>(['arch', 'quantization', 'graph_mode'])
  const explorerRows = useMemo(() => computeCoveredCombos(tests, explorerDims), [tests, explorerDims])
  const [comboFilter, setComboFilter] = useState<Record<string, string> | null>(null)

  const explorerFiltered = useMemo(() => {
    if (!comboFilter) return filtered
    return filtered.filter((t) => {
      for (const [dim, val] of Object.entries(comboFilter)) {
        const arr = t.coverage[dim as DimKey]
        if (!arr || !arr.includes(val)) return false
      }
      return true
    })
  }, [filtered, comboFilter])

  const explorerGrouped = [1, 2, 4].map((c) => ({ card: c, items: explorerFiltered.filter((t) => t.card_count === c) })).filter((g) => g.items.length)

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={5}><Card loading={isLoading}><Statistic title="总测试" value={summary?.total_tests ?? 0} /></Card></Col>
        <Col span={7}>
          <Card loading={isLoading}>
            <Statistic
              title="已标记测试"
              value={summary?.marked_tests ?? 0}
              suffix={`/ ${summary?.total_tests ?? 0}`}
              valueStyle={{ color: '#1890ff' }}
            />
            <Progress
              percent={Math.round((summary?.marked_ratio ?? 0) * 100)}
              size="small"
              strokeColor={(summary?.marked_ratio ?? 0) < 0.2 ? '#ff4d4f' : '#1890ff'}
              format={() => `${Math.round((summary?.marked_ratio ?? 0) * 100)}%`}
            />
          </Card>
        </Col>
        <Col span={4}><Card loading={isLoading}><Statistic title="1 卡" value={summary?.by_card?.['1'] ?? 0} /></Card></Col>
        <Col span={4}><Card loading={isLoading}><Statistic title="2 卡" value={summary?.by_card?.['2'] ?? 0} /></Card></Col>
        <Col span={4}><Card loading={isLoading}><Statistic title="4 卡" value={summary?.by_card?.['4'] ?? 0} /></Card></Col>
      </Row>

      <Card title="交叉覆盖探索器" size="small" style={{ marginBottom: 16 }}
        extra={<Text type="secondary" style={{ fontSize: 12 }}>
          {explorerDims.length > 0 ? `已覆盖组合：${explorerRows.length} · 测试总数：${explorerRows.reduce((s, r) => s + r.count, 0)}` : '请选择维度'}
        </Text>}>
        <Space wrap style={{ marginBottom: 12 }}>
          {DIM_ORDER.map((d) => (
            <Checkbox
              key={d}
              checked={explorerDims.includes(d)}
              onChange={(e) => {
                setComboFilter(null)
                setExplorerDims(e.target.checked ? [...explorerDims, d] : explorerDims.filter((x) => x !== d))
              }}
            >
              {DIM_LABEL[d]}
            </Checkbox>
          ))}
        </Space>
        <Space wrap style={{ marginBottom: 12 }}>
          {Object.entries(PRESETS).map(([label, dims]) => (
            <Button key={label} size="small" type={explorerDims.length === dims.length && dims.every((d) => explorerDims.includes(d)) ? 'primary' : 'default'}
              onClick={() => { setComboFilter(null); setExplorerDims(dims) }}>
              {label}
            </Button>
          ))}
          {comboFilter && (
            <Button size="small" type="link" danger onClick={() => setComboFilter(null)}>
              清除组合筛选 ✕
            </Button>
          )}
        </Space>
        {explorerDims.length > 0 && explorerRows.length > 0 ? (
          <Table
            dataSource={explorerRows}
            rowKey="key"
            size="small"
            pagination={{ pageSize: 15, showTotal: (t) => `共 ${t} 个组合` }}
            scroll={{ x: 500 }}
            columns={[
              ...explorerDims.map((d, i) => ({
                title: DIM_LABEL[d], key: d, width: 140,
                render: (_: unknown, r: ComboRow) => <Tag color={TAG_COLORS[d]}>{r.combo[i]}</Tag>,
              })),
              {
                title: '测试数', dataIndex: 'count', key: 'count', width: 80,
                sorter: (a: ComboRow, b: ComboRow) => a.count - b.count,
                render: (count: number, r: ComboRow) => (
                  <Button type="link" size="small" onClick={() => {
                    const filter: Record<string, string> = {}
                    explorerDims.forEach((d, i) => { filter[d] = r.combo[i] })
                    setComboFilter(filter)
                  }}>
                    {count}
                  </Button>
                ),
              },
            ]}
          />
        ) : <Empty description={explorerDims.length === 0 ? '请选择至少一个维度' : '无覆盖组合'} />}
      </Card>

      <Card>
        <Space wrap style={{ marginBottom: 16 }}>
          <Input.Search placeholder="搜索测试名/模型/标签" allowClear style={{ width: 260 }} onChange={(e) => setSearch(e.target.value)} />
          <Select placeholder="卡数" allowClear style={{ width: 120 }} onChange={setCard}
            options={[{ label: '1 卡', value: '1' }, { label: '2 卡', value: '2' }, { label: '4 卡', value: '4' }]} />
          <Select placeholder="架构" allowClear style={{ width: 150 }} onChange={setArch} options={archOpts} />
          <Select placeholder="图模式" allowClear style={{ width: 160 }} onChange={setGraph} options={graphOpts} />
          <Checkbox checked={showUnmarked} onChange={(e) => setShowUnmarked(e.target.checked)}>显示未标记</Checkbox>
          <Button icon={<DownloadOutlined />} onClick={exportCSV}>导出 CSV</Button>
        </Space>

        {comboFilter && (
          <div style={{ marginBottom: 12 }}>
            <Tag color="blue" closable onClose={() => setComboFilter(null)}>
              组合筛选：{Object.entries(comboFilter).map(([d, v]) => `${DIM_LABEL[d] ?? d}=${v}`).join(' & ')}
            </Tag>
          </div>
        )}

        {data && !tests.length ? <Empty description="暂无 E2E 覆盖数据（请先同步）" /> : (
          (comboFilter ? explorerGrouped : grouped).length ? (comboFilter ? explorerGrouped : grouped).map((g) => (
            <div key={g.card} style={{ marginBottom: 16 }}>
              <Text strong style={{ fontSize: 14 }}>{g.card} 卡测试（{g.items.length}）</Text>
              <Table
                dataSource={g.items}
                rowKey={(r) => `${r.filepath}-${r.test_name}`}
                columns={columns}
                size="small"
                pagination={false}
                scroll={{ x: 1500 }}
                rowClassName={(r) => (r.is_marked ? '' : 'unmarked-row')}
                style={{ marginTop: 8 }}
              />
            </div>
          )) : <Empty description="无匹配测试" />
        )}
      </Card>
    </div>
  )
}
