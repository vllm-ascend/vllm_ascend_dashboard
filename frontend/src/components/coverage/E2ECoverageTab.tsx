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
    const rows = filtered.map((t) => [
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
    ...(['arch', 'feature', 'parallel', 'deploy', 'hardware', 'quantization', 'graph_mode'] as const).map((dim) => ({
      title: DIM_LABEL[dim], key: dim, width: 120,
      render: (_: unknown, r: E2ETestItem) => tags(r.coverage[dim], dim),
    })),
  ]

  const grouped = [1, 2, 4].map((c) => ({ card: c, items: filtered.filter((t) => t.card_count === c) })).filter((g) => g.items.length)

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

        {data && !tests.length ? <Empty description="暂无 E2E 覆盖数据（请先同步）" /> : (
          grouped.length ? grouped.map((g) => (
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
