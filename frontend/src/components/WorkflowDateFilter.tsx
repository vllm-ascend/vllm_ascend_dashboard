import { DatePicker, Select, Space } from 'antd'
import dayjs, { Dayjs } from 'dayjs'

const { RangePicker } = DatePicker

export type DateFilterMode = 'recent_day' | 'recent_week' | 'custom' | 'all'

export type StoredDateRange = {
  start: string | null
  end: string | null
}

export interface WorkflowDateFilterPreferences {
  dateFilterMode?: DateFilterMode
  dateRange?: StoredDateRange | null
}

export const getDateRangeForMode = (
  mode: DateFilterMode,
  baseDate = dayjs(),
): [Dayjs, Dayjs] | null => {
  if (mode === 'recent_day') {
    return [baseDate.startOf('day'), baseDate.endOf('day')]
  }
  if (mode === 'recent_week') {
    return [baseDate.subtract(6, 'day').startOf('day'), baseDate.endOf('day')]
  }
  return null
}

export function getInitialDateFilterMode(
  preferences: WorkflowDateFilterPreferences,
): DateFilterMode {
  if (preferences.dateFilterMode) return preferences.dateFilterMode
  if (preferences.dateRange === null) return 'all'
  if (!preferences.dateRange?.start && !preferences.dateRange?.end) return 'recent_day'

  const today = dayjs()
  const start = preferences.dateRange.start ? dayjs(preferences.dateRange.start) : null
  const end = preferences.dateRange.end ? dayjs(preferences.dateRange.end) : null
  if (start?.isSame(today, 'day') && end?.isSame(today, 'day')) return 'recent_day'
  if (start?.isSame(today.subtract(6, 'day'), 'day') && end?.isSame(today, 'day')) return 'recent_week'
  return 'custom'
}

export function getInitialCustomDateRange(
  preferences: WorkflowDateFilterPreferences,
  mode: DateFilterMode,
): [Dayjs | null, Dayjs | null] | null {
  if (mode !== 'custom' || !preferences.dateRange) return null
  return [
    preferences.dateRange.start ? dayjs(preferences.dateRange.start) : null,
    preferences.dateRange.end ? dayjs(preferences.dateRange.end) : null,
  ]
}

interface WorkflowDateFilterProps {
  mode: DateFilterMode
  customDateRange: [Dayjs | null, Dayjs | null] | null
  onModeChange: (mode: DateFilterMode) => void
  onRangeChange: (range: [Dayjs | null, Dayjs | null] | null) => void
}

export function WorkflowDateFilter({
  mode,
  customDateRange,
  onModeChange,
  onRangeChange,
}: WorkflowDateFilterProps) {
  return (
    <Space.Compact>
      <Select
        value={mode}
        options={[
          { label: '最近一天', value: 'recent_day' },
          { label: '最近一周', value: 'recent_week' },
          { label: '自定义日期', value: 'custom' },
          { label: '全部日期', value: 'all' },
        ]}
        onChange={(value: DateFilterMode) => onModeChange(value)}
        style={{ width: 130 }}
      />
      {mode === 'custom' && (
        <RangePicker
          value={customDateRange as any}
          onChange={(dates) => onRangeChange(dates as [Dayjs | null, Dayjs | null] | null)}
          allowClear
          format="YYYY-MM-DD"
          style={{ width: 240 }}
        />
      )}
    </Space.Compact>
  )
}
