import { describe, expect, it } from 'vitest'

import {
  buildNightlyCsv,
  fmtHour,
  fmtSpan,
  fmtTime,
  quoteCsv,
} from './nightlyGanttUtils'
import type { NightlyGanttItem } from '../services/ci'

function makeItem(over: Partial<NightlyGanttItem> = {}): NightlyGanttItem {
  return {
    phase: 'Single-node',
    name: 'Test-Case',
    raw_name: 'single-node (main, Test-Case, config.yaml)',
    start_bj: '08:00:00',
    end_bj: '08:30:00',
    start_ms: 0,
    end_ms: 0,
    duration: '30m',
    duration_seconds: 1800,
    status: 'ok',
    conclusion: 'success',
    job_id: 1,
    job_url: null,
    ...over,
  }
}

describe('buildNightlyCsv', () => {
  it('starts with UTF-8 BOM and the fixed header', () => {
    const csv = buildNightlyCsv([])
    expect(csv.startsWith('\ufeff')).toBe(true)
    expect(csv).toBe('\ufeff阶段,用例名称,开始时间(北京),结束时间(北京),耗时')
  })

  it('emits one data row per item joined by newline', () => {
    const csv = buildNightlyCsv([
      makeItem({ phase: 'Multi-node', name: 'A', start_bj: '08:00:00', end_bj: '08:30:00', duration: '30m' }),
      makeItem({ phase: 'Single-node', name: 'B', start_bj: '09:00:00', end_bj: '09:10:00', duration: '10m' }),
    ])
    const lines = csv.split('\n')
    expect(lines).toHaveLength(3)
    expect(lines[0]).toBe('\ufeff阶段,用例名称,开始时间(北京),结束时间(北京),耗时')
    expect(lines[1]).toBe('Multi-node,A,08:00:00,08:30:00,30m')
    expect(lines[2]).toBe('Single-node,B,09:00:00,09:10:00,10m')
  })

  it('matches the original nightly_report.py column order exactly', () => {
    const csv = buildNightlyCsv([makeItem({ phase: 'Double-node', name: 'X', start_bj: '10:00:00', end_bj: '10:05:00', duration: '5m' })])
    const dataLine = csv.split('\n')[1]
    expect(dataLine).toBe('Double-node,X,10:00:00,10:05:00,5m')
  })

  it('quotes fields containing comma or double-quote', () => {
    const csv = buildNightlyCsv([
      makeItem({ name: 'Case,With,Commas', start_bj: '08:00:00', end_bj: '08:30:00', duration: '30m' }),
      makeItem({ name: 'Case"With"Quote', start_bj: '09:00:00', end_bj: '09:10:00', duration: '10m' }),
    ])
    const lines = csv.split('\n')
    // 含逗号 -> 双引号包裹
    expect(lines[1]).toBe('Single-node,"Case,With,Commas",08:00:00,08:30:00,30m')
    // 含双引号 -> 双引号包裹 + 内部双引号翻倍
    expect(lines[2]).toBe('Single-node,"Case""With""Quote",09:00:00,09:10:00,10m')
  })
})

describe('quoteCsv', () => {
  it('leaves plain values untouched', () => {
    expect(quoteCsv('plain')).toBe('plain')
    expect(quoteCsv('a-b-c')).toBe('a-b-c')
  })

  it('wraps values containing a comma in double quotes', () => {
    expect(quoteCsv('a,b')).toBe('"a,b"')
  })

  it('wraps values containing a double-quote and doubles inner quotes', () => {
    expect(quoteCsv('a"b')).toBe('"a""b"')
  })
})

describe('fmtHour / fmtTime (UTC+8 跨日处理)', () => {
  // UTC 2026-03-23 16:00 = 北京 2026-03-24 00:00（跨日）
  const CROSS_DAY_MS = Date.UTC(2026, 2, 23, 16, 0, 0)
  // UTC 2026-03-23 00:00 = 北京 2026-03-23 08:00（同日）
  const SAME_DAY_MS = Date.UTC(2026, 2, 23, 0, 0, 0)

  it('fmtHour carries the date so cross-day hours do not wrap back', () => {
    // 跨日：UTC 16:00 -> 北京次日 00:00，日期必须进位到 03/24
    expect(fmtHour(CROSS_DAY_MS)).toBe('03/24 00:00')
    // 同日：UTC 00:00 -> 北京当天 08:00
    expect(fmtHour(SAME_DAY_MS)).toBe('03/23 08:00')
  })

  it('fmtHour produces monotonically increasing labels across the UTC 16:00 boundary', () => {
    // UTC 15:00 -> 北京 23:00；UTC 16:00 -> 北京次日 00:00；不应出现小时回绕
    const before = fmtHour(Date.UTC(2026, 2, 23, 15, 0, 0))
    const after = fmtHour(Date.UTC(2026, 2, 23, 16, 0, 0))
    expect(before).toBe('03/23 23:00')
    expect(after).toBe('03/24 00:00')
    // 日期不同即可证明未发生回绕混淆
    expect(before.split(' ')[0]).not.toBe(after.split(' ')[0])
  })

  it('fmtTime carries the date for cross-day timestamps', () => {
    expect(fmtTime(CROSS_DAY_MS)).toBe('03/24 00:00:00')
    expect(fmtTime(SAME_DAY_MS)).toBe('03/23 08:00:00')
  })
})

describe('fmtSpan', () => {
  it('formats sub-minute durations as seconds', () => {
    expect(fmtSpan(0)).toBe('0s')
    expect(fmtSpan(5 * 1000)).toBe('5s')
    expect(fmtSpan(59 * 1000)).toBe('59s')
  })

  it('formats minute-only durations without trailing seconds when s==0', () => {
    expect(fmtSpan(5 * 60 * 1000)).toBe('5m')
    expect(fmtSpan(5 * 60 * 1000 + 30 * 1000)).toBe('5m30s')
  })

  it('formats hour durations', () => {
    expect(fmtSpan(60 * 60 * 1000)).toBe('1h0m')
    expect(fmtSpan(83 * 60 * 1000)).toBe('1h23m')
  })
})
