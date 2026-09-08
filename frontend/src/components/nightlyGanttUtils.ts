/**
 * Nightly 执行甘特图纯函数工具
 *
 * 从 NightlyGanttTab.tsx 提取，便于单测且不引入 antd/CSS 依赖。
 */
import type { NightlyGanttItem } from '../services/ci'

export const HOUR = 3600 * 1000
export const BJ_OFFSET_MS = 8 * 3600 * 1000

/**
 * 格式化整点标签（北京时间）。用 new Date(ms+8h) 取 UTC 部分，避免 (h+8)%24 在跨 UTC 16:00（北京次日 00:00）时回绕；带日期前缀以区分跨日。
 */
export function fmtHour(ms: number): string {
  const d = new Date(ms + BJ_OFFSET_MS)
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(d.getUTCDate()).padStart(2, '0')
  const hh = String(d.getUTCHours()).padStart(2, '0')
  return `${mm}/${dd} ${hh}:00`
}

/**
 * 格式化完整时间（北京时间 HH:MM:SS，带日期前缀）。
 */
export function fmtTime(ms: number): string {
  const d = new Date(ms + BJ_OFFSET_MS)
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(d.getUTCDate()).padStart(2, '0')
  const hh = String(d.getUTCHours()).padStart(2, '0')
  const mi = String(d.getUTCMinutes()).padStart(2, '0')
  const ss = String(d.getUTCSeconds()).padStart(2, '0')
  return `${mm}/${dd} ${hh}:${mi}:${ss}`
}

/** 毫秒跨度 -> 人类可读时长（与后端 format_duration 一致：h>0 显示 Xh Ym；m>0 且 s>0 显示 Xm Ys，s==0 显示 Xm；否则 Xs）。 */
export function fmtSpan(ms: number): string {
  const totalSec = Math.floor(ms / 1000)
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  if (h > 0) return `${h}h${m}m`
  if (m > 0) return s > 0 ? `${m}m${s}s` : `${m}m`
  return `${s}s`
}

/** CSV 字段转义：含逗号或双引号时用双引号包裹，内部双引号翻倍。 */
export function quoteCsv(value: string): string {
  if (value.includes(',') || value.includes('"')) {
    return `"${value.replace(/"/g, '""')}"`
  }
  return value
}

export const CSV_HEADER = '阶段,用例名称,开始时间(北京),结束时间(北京),耗时'

/**
 * 构造 Nightly 甘特图 CSV 字符串（与 nightly_report.py 输出格式一致）。
 * 含 UTF-8 BOM 以兼容 Excel，行用 \n 分隔，字段用 quoteCsv 转义。
 */
export function buildNightlyCsv(rows: NightlyGanttItem[]): string {
  const lines = [CSV_HEADER]
  rows.forEach((r) => {
    lines.push([r.phase, r.name, r.start_bj, r.end_bj, r.duration].map(quoteCsv).join(','))
  })
  return '\ufeff' + lines.join('\n')
}
