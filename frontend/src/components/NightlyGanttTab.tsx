import { useMemo, useRef, useState } from 'react'
import { Card, Col, Empty, InputNumber, Row, Select, Space, Statistic, Table, Tooltip, Button, message } from 'antd'
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
const STATUS_META: Record<string, { color: string; text: string }> = {
  ok: { color: '#059669', text: '成功' },
  err: { color: '#dc2626', text: '失败' },
  cancelled: { color: '#d97706', text: '取消' },
}

const tableColumns: ColumnsType<NightlyGanttItem> = [
  { title: '用例名称', dataIndex: 'name', key: 'name', ellipsis: true },
  { title: '创建', dataIndex: 'created_bj', key: 'created_bj', width: 90, render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v}</span> },
  { title: '开始', dataIndex: 'start_bj', key: 'start_bj', width: 90, render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v}</span> },
  { title: '结束', dataIndex: 'end_bj', key: 'end_bj', width: 90, render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v}</span> },
  {
    title: '排队', dataIndex: 'queued_ms', key: 'queued_ms', width: 80, align: 'right',
    render: (v: number) => <span style={{ fontFamily: 'monospace', color: '#9ca0b3' }}>{fmtSpan(v)}</span>,
  },
  {
    title: '耗时', dataIndex: 'duration', key: 'duration', width: 90, align: 'right',
    render: (v: string, r: NightlyGanttItem) => (
      <span style={{ fontFamily: 'monospace', color: STATUS_META[r.status]?.color ?? '#999', fontWeight: 600 }}>{v}</span>
    ),
  },
  {
    title: '状态', dataIndex: 'status', key: 'status', width: 70, align: 'center',
    render: (v: string) => {
      const m = STATUS_META[v] || { color: '#999', text: v }
      return <span style={{ color: m.color, fontWeight: 600 }}>{m.text}</span>
    },
  },
]

interface GanttViewProps {
  rows: NightlyGanttItem[]
  phases: Record<string, NightlyGanttItem[]>
}

function GanttView({ rows, phases }: GanttViewProps) {
  const tipRef = useRef<HTMLDivElement>(null)

  const { gStart, gHours, gTotal } = useMemo(() => {
    if (!rows.length) return { gStart: 0, gHours: 0, gTotal: 0 }
    const allCreated = Math.min(...rows.map((r) => r.created_ms))
    const allEnd = Math.max(...rows.map((r) => r.end_ms))
    const gStartCalc = Math.floor(allCreated / HOUR) * HOUR
    const gEndCalc = Math.ceil(allEnd / HOUR) * HOUR
    return {
      gStart: gStartCalc,
      gHours: Math.round((gEndCalc - gStartCalc) / HOUR),
      gTotal: gEndCalc - gStartCalc,
    }
  }, [rows])

  if (!rows.length) {
    return <Empty description="该 run 无可用例数据" />
  }

  const hours: number[] = []
  for (let i = 0; i < gHours; i++) hours.push(gStart + i * HOUR)
  const pct = (ms: number) => (gTotal > 0 ? ((ms - gStart) / gTotal) * 100 : 0)

  const moveTip = (e: React.MouseEvent) => {
    const el = tipRef.current
    if (!el) return
    let x = e.clientX + 14
    let y = e.clientY + 14
    const w = el.offsetWidth
    const h = el.offsetHeight
    if (x + w > window.innerWidth - 8) x = e.clientX - w - 14
    if (y + h > window.innerHeight - 8) y = e.clientY - h - 14
    el.style.left = `${x}px`
    el.style.top = `${y}px`
  }
  const showTip = (e: React.MouseEvent, r: NightlyGanttItem) => {
    const el = tipRef.current
    if (!el) return
    const m = STATUS_META[r.status] || { color: '#999', text: r.status }
    el.innerHTML =
      `<div class="tt-name">${r.name}</div>` +
      `<div class="tt-row"><span class="tt-label">状态</span><span class="tt-status ${r.status}">${m.text}</span></div>` +
      `<div class="tt-row"><span class="tt-label">创建</span><span class="tt-val">${fmtTime(r.created_ms)}</span></div>` +
      `<div class="tt-row"><span class="tt-label">开始</span><span class="tt-val">${fmtTime(r.start_ms)}</span></div>` +
      `<div class="tt-row"><span class="tt-label">结束</span><span class="tt-val">${fmtTime(r.end_ms)}</span></div>` +
      `<div class="tt-row"><span class="tt-label">排队</span><span class="tt-val">${fmtSpan(r.queued_ms)}</span></div>` +
      `<div class="tt-row"><span class="tt-label">执行</span><span class="tt-val">${r.duration}</span></div>`
    el.style.display = 'block'
    moveTip(e)
  }
  const hideTip = () => {
    const el = tipRef.current
    if (el) el.style.display = 'none'
  }

  return (
    <div className="gantt-wrap">
      <div className="gantt-tooltip" ref={tipRef} style={{ display: 'none' }} />
      <div className="gantt">
        {PHASE_ORDER.map((phase) => {
          const items = phases[phase] || []
          if (!items.length) return null
          const okN = items.filter((r) => r.status === 'ok').length
          const errN = items.filter((r) => r.status === 'err').length
          const canN = items.filter((r) => r.status === 'cancelled').length
          return (
            <div className="gantt-section" key={phase}>
              <div className="gantt-phase">
                <span className={`badge ${PHASE_BADGE[phase]}`}>{phase}</span>
                <span className="gantt-phase-count">
                  {items.length} jobs · {okN} ok / {errN} fail{canN ? ` / ${canN} cancel` : ''}
                </span>
              </div>
              <div className="gantt-chart-area">
                <div className="gantt-axis">
                  <div className="gantt-axis-spacer" />
                  <div className="gantt-axis-bar">
                    {hours.map((ms) => (
                      <div className="gantt-hour-label" key={ms} style={{ left: `${pct(ms).toFixed(2)}%` }}>
                        {fmtHour(ms)}
                      </div>
                    ))}
                  </div>
                </div>
                {items.map((r) => {
                  const waitLeft = pct(r.created_ms)
                  const waitWidth = Math.max(pct(r.start_ms) - waitLeft, r.queued_ms > 0 ? 0.3 : 0)
                  const runLeft = pct(r.start_ms)
                  const runWidth = Math.max(pct(r.end_ms) - runLeft, 0.3)
                  return (
                    <div className="gantt-row" key={`${r.phase}-${r.job_id ?? r.name}`}>
                      <Tooltip title={r.name}>
                        <div className="gantt-label">{r.name}</div>
                      </Tooltip>
                      <div className="gantt-track">
                        {hours.map((ms) => (
                          <div className="gantt-grid" key={ms} style={{ left: `${pct(ms).toFixed(2)}%` }} />
                        ))}
                        {r.queued_ms > 0 && (
                          <div
                            className={`gantt-bar wait ${r.status}`}
                            style={{ left: `${waitLeft.toFixed(2)}%`, width: `${waitWidth.toFixed(2)}%` }}
                            onMouseEnter={(e) => showTip(e, r)}
                            onMouseMove={moveTip}
                            onMouseLeave={hideTip}
                          />
                        )}
                        <div
                          className={`gantt-bar run ${r.status}`}
                          style={{ left: `${runLeft.toFixed(2)}%`, width: `${runWidth.toFixed(2)}%` }}
                          onMouseEnter={(e) => showTip(e, r)}
                          onMouseMove={moveTip}
                          onMouseLeave={hideTip}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
      <div className="gantt-legend">
        <span className="lg-item"><span className="lg-sw ok" />成功</span>
        <span className="lg-item"><span className="lg-sw err" />失败</span>
        <span className="lg-item"><span className="lg-sw cancelled" />取消</span>
        <span className="lg-item"><span className="lg-sw wait" />排队等待</span>
        <span className="lg-note">悬停条形查看详情 · 北京时间 (UTC+8)</span>
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
        <Col span={4}><Card><Statistic title="用例总数" value={kpi.total} /></Card></Col>
        <Col span={4}>
          <Card><Statistic title="成功" value={kpi.ok} valueStyle={{ color: '#059669' }} suffix={kpi.total ? `(${Math.round(kpi.ok_rate * 100)}%)` : ''} /></Card>
        </Col>
        <Col span={4}>
          <Card><Statistic title="失败" value={kpi.err} valueStyle={{ color: '#dc2626' }} suffix={kpi.total ? `(${Math.round(kpi.err_rate * 100)}%)` : ''} /></Card>
        </Col>
        <Col span={4}>
          <Card><Statistic title="取消" value={kpi.cancelled} valueStyle={{ color: '#d97706' }} suffix={kpi.total ? `(${Math.round(kpi.cancel_rate * 100)}%)` : ''} /></Card>
        </Col>
        <Col span={4}>
          <Card><Statistic title="时间跨度" value={kpi.span_ms ? fmtSpan(kpi.span_ms) : '—'} /></Card>
        </Col>
        <Col span={4}>
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
                  scroll={{ x: 560 }}
                />
              </div>
            )
          })}
          <div className="note">仅包含测试用例，不含基础设施 Job。条形分两段：斜纹=排队等待(created→started)，实色=执行(started→completed)。所有时间已转换为北京时间 (UTC+8)。数据来源：GitHub Actions API。</div>
        </>
      )}
    </div>
  )
}

export default NightlyGanttTab
