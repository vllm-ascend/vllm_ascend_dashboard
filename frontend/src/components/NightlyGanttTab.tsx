import { useState, useMemo } from 'react'
import { Card, Col, Empty, InputNumber, Row, Select, Space, Statistic, Table, Tooltip, message, Button } from 'antd'
import { DownloadOutlined, FieldTimeOutlined, SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useNightlyGantt, useRuns } from '../hooks/useCI'
import type { CIResult, NightlyGanttItem } from '../services/ci'
import { HOUR, fmtHour, fmtTime, fmtSpan, buildNightlyCsv } from './nightlyGanttUtils'
import './NightlyGanttTab.css'

const PHASE_ORDER = ['Multi-node', 'Double-node', 'Single-node'] as const
const PHASE_BADGE: Record<string, string> = {
  'Multi-node': 'b-multi',
  'Double-node': 'b-double',
  'Single-node': 'b-single',
}
const HARDWARE_TO_WORKFLOW: Record<string, string> = {
  a3: 'Nightly-A3',
  a2: 'Nightly-A2',
}

const tableColumns: ColumnsType<NightlyGanttItem> = [
  { title: '用例名称', dataIndex: 'name', key: 'name', ellipsis: true },
  { title: '开始', dataIndex: 'start_bj', key: 'start_bj', width: 100, render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v}</span> },
  { title: '结束', dataIndex: 'end_bj', key: 'end_bj', width: 100, render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v}</span> },
  {
    title: '耗时', dataIndex: 'duration', key: 'duration', width: 90, align: 'right',
    render: (v: string, r: NightlyGanttItem) => (
      <span style={{ fontFamily: 'monospace', color: r.status === 'ok' ? '#059669' : '#dc2626', fontWeight: 600 }}>{v}</span>
    ),
  },
  {
    title: '状态', dataIndex: 'status', key: 'status', width: 70, align: 'center',
    render: (v: string) => (
      <span style={{ color: v === 'ok' ? '#059669' : '#dc2626', fontWeight: 600 }}>
        {v === 'ok' ? '成功' : '失败'}
      </span>
    ),
  },
]

interface GanttViewProps {
  rows: NightlyGanttItem[]
  phases: Record<string, NightlyGanttItem[]>
}

function GanttView({ rows, phases }: GanttViewProps) {
  const { gStart, gHours, gTotal } = useMemo(() => {
    if (!rows.length) {
      return { gStart: 0, gHours: 0, gTotal: 0 }
    }
    const allStart = Math.min(...rows.map((r) => r.start_ms))
    const allEnd = Math.max(...rows.map((r) => r.end_ms))
    const gStartCalc = Math.floor(allStart / HOUR) * HOUR
    const gEndCalc = Math.ceil(allEnd / HOUR) * HOUR
    const gTotalCalc = gEndCalc - gStartCalc
    return {
      gStart: gStartCalc,
      gHours: Math.round(gTotalCalc / HOUR),
      gTotal: gTotalCalc,
    }
  }, [rows])

  if (!rows.length) {
    return <Empty description="该 run 无可用例数据" />
  }

  const hours: number[] = []
  for (let i = 0; i < gHours; i++) hours.push(gStart + i * HOUR)

  return (
    <div className="gantt-wrap">
      <div className="gantt">
        <div className="gantt-header">
          {hours.map((ms) => (
            <div key={ms} className="gantt-hour">{fmtHour(ms)}</div>
          ))}
        </div>
        {PHASE_ORDER.map((phase) => {
          const items = phases[phase] || []
          if (!items.length) return null
          return (
            <div key={phase}>
              <div className="gantt-phase">{phase}</div>
              {items.map((r) => {
                const left = gTotal > 0 ? ((r.start_ms - gStart) / gTotal) * 100 : 0
                const width = gTotal > 0 ? Math.max(((r.end_ms - r.start_ms) / gTotal) * 100, 0.3) : 0.3
                const tip = `${r.name}\n${fmtTime(r.start_ms)} -> ${fmtTime(r.end_ms)}\n${r.duration}\n${r.status === 'ok' ? '成功' : '失败'}`
                return (
                  <div className="gantt-row" key={`${r.phase}-${r.job_id ?? r.name}`}>
                    <Tooltip title={r.name}>
                      <div className="gantt-label">{r.name}</div>
                    </Tooltip>
                    <div className="gantt-track">
                      <Tooltip title={tip}>
                        <div
                          className={`gantt-bar ${r.status}`}
                          style={{ left: `${left.toFixed(2)}%`, width: `${width.toFixed(2)}%` }}
                        />
                      </Tooltip>
                    </div>
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function NightlyGanttTab() {
  const [runInput, setRunInput] = useState<number | null>(null)
  const [runNumber, setRunNumber] = useState<number | null>(null)
  const [hardware, setHardware] = useState<string>('a3')
  const { data, isLoading, error, isFetching } = useNightlyGantt(runNumber, hardware)
  const workflowName = HARDWARE_TO_WORKFLOW[hardware] || 'Nightly-A3'
  const { data: recentRuns } = useRuns({ workflow_name: workflowName, limit: 20 })

  const onSearch = () => {
    if (!runInput || runInput <= 0) {
      message.warning('请输入有效的 Run #')
      return
    }
    setRunNumber(runInput)
  }

  const onExportCsv = () => {
    if (!data || !data.rows.length) {
      message.warning('暂无数据可导出')
      return
    }
    const blob = new Blob([buildNightlyCsv(data.rows)], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `nightly-${data.hardware.toLowerCase()}-${data.run_number}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const kpi = data?.kpi
  const renderKpi = () => {
    if (!kpi) return null
    return (
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}>
          <Card><Statistic title="用例总数" value={kpi.total} /></Card>
        </Col>
        <Col span={4}>
          <Card><Statistic title="成功" value={kpi.ok} valueStyle={{ color: '#059669' }} suffix={kpi.total ? `(${Math.round(kpi.ok_rate * 100)}%)` : ''} /></Card>
        </Col>
        <Col span={4}>
          <Card><Statistic title="失败" value={kpi.err} valueStyle={{ color: '#dc2626' }} suffix={kpi.total ? `(${Math.round(kpi.err_rate * 100)}%)` : ''} /></Card>
        </Col>
        <Col span={4}>
          <Card><Statistic title="时间跨度" value={kpi.span_ms ? fmtSpan(kpi.span_ms) : '—'} /></Card>
        </Col>
        <Col span={8}>
          <Card title="阶段分布" size="small">
            <Space size={8} wrap>
              {PHASE_ORDER.map((p) => (
                <span key={p} className={`badge ${PHASE_BADGE[p]}`} style={{ fontSize: 11, fontWeight: 600, padding: '2px 7px', borderRadius: 3 }}>
                  {p}: {kpi.phase_counts[p] || 0}
                </span>
              ))}
            </Space>
          </Card>
        </Col>
      </Row>
    )
  }

  return (
    <div className="nightly-gantt-page">
      <Card style={{ marginBottom: 16 }}>
        <Space size={12} wrap>
          <span style={{ fontWeight: 600, fontSize: 15 }}>
            <FieldTimeOutlined style={{ marginRight: 6 }} />
            Nightly 执行甘特图
          </span>
          <InputNumber
            placeholder="Run #"
            min={1}
            style={{ width: 140 }}
            value={runInput ?? undefined}
            onChange={(v) => setRunInput(v as number | null)}
            onPressEnter={onSearch}
          />
          <Select
            showSearch
            placeholder="或选择最近 Run"
            style={{ width: 280 }}
            optionFilterProp="label"
            value={runNumber ?? undefined}
            onChange={(v) => {
              setRunInput(v)
              setRunNumber(v)
            }}
            options={(recentRuns || []).map((r: CIResult) => ({
              label: `#${r.run_number ?? '-'} · ${r.conclusion || r.status || '-'} · ${r.started_at ? new Date(r.started_at).toLocaleString('zh-CN') : ''}`,
              value: r.run_number ?? 0,
              disabled: !r.run_number,
            }))}
          />
          <Select
            style={{ width: 100 }}
            value={hardware}
            onChange={setHardware}
            options={[
              { label: 'A3', value: 'a3' },
              { label: 'A2', value: 'a2' },
            ]}
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={onSearch} loading={isFetching}>
            查询
          </Button>
          <Button icon={<DownloadOutlined />} onClick={onExportCsv} disabled={!data || !data.rows.length}>
            导出 CSV
          </Button>
          {data?.run_meta?.html_url && (
            <a href={data.run_meta.html_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 13, color: '#1890ff' }}>
              GitHub Actions Run #{data.run_number}
            </a>
          )}
        </Space>
      </Card>

      {error && (
        <Card style={{ marginBottom: 16 }}>
          <Empty description={error instanceof Error ? error.message : '查询失败'} />
        </Card>
      )}

      {isLoading && <Card loading />}

      {data && !error && (
        <>
          {renderKpi()}
          <GanttView rows={data.rows} phases={data.phases} />
          {PHASE_ORDER.map((phase) => {
            const items = data.phases[phase] || []
            return (
              <div key={phase} style={{ marginBottom: 16 }}>
                <h2>
                  <span className={`badge ${PHASE_BADGE[phase]}`}>{phase}</span>
                  <span style={{ fontSize: 12, color: '#999', fontWeight: 400 }}>（{items.length} 条）</span>
                </h2>
                <Table
                  dataSource={items}
                  rowKey={(r: NightlyGanttItem) => `${r.phase}-${r.job_id ?? r.name}`}
                  columns={tableColumns}
                  pagination={false}
                  size="small"
                  scroll={{ x: 480 }}
                />
              </div>
            )
          })}
          <div className="note">仅包含测试用例，不含基础设施 Job。所有时间已转换为北京时间 (UTC+8)。数据来源：GitHub Actions API。</div>
        </>
      )}
    </div>
  )
}

export default NightlyGanttTab
