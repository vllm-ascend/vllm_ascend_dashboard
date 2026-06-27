import { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import {
  Checkbox,
  Radio,
  Input,
  DatePicker,
  Divider,
  Pagination,
  Spin,
} from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useLogSources, useLogQuery } from '../hooks/useLogs'
import type { LogQueryRequest } from '../services/logs'
import LogEntryRow from '../components/LogEntry'
import dayjs from 'dayjs'
import './LogCenter.css'

const { RangePicker } = DatePicker

const SOURCE_OPTIONS = [
  { label: 'Claude CLI', value: 'claude_cli' },
  { label: '失败分析', value: 'failure_analysis' },
  { label: '应用日志', value: 'app' },
  { label: '调度器', value: 'scheduler' },
]

const LEVEL_OPTIONS = [
  { label: 'ERROR', value: 'error' },
  { label: 'WARNING', value: 'warning' },
  { label: 'INFO', value: 'info' },
  { label: 'DEBUG', value: 'debug' },
]

const TIME_PRESETS = [
  { label: '最近 1 小时', value: '1h' },
  { label: '最近 24 小时', value: '24h' },
  { label: '最近 7 天', value: '7d' },
  { label: '自定义', value: 'custom' },
]

function LogCenter() {
  const [selectedSources, setSelectedSources] = useState<string[]>([
    'claude_cli',
    'failure_analysis',
    'app',
    'scheduler',
  ])
  const [selectedLevels, setSelectedLevels] = useState<string[]>([
    'error',
    'warning',
    'info',
  ])
  const [timePreset, setTimePreset] = useState('24h')
  const [customRange, setCustomRange] = useState<
    [dayjs.Dayjs, dayjs.Dayjs] | null
  >(null)
  const [searchText, setSearchText] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = e.target.value
      setSearchText(val)
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(() => {
        setDebouncedSearch(val)
        setPage(1)
      }, 300)
    },
    []
  )

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  // Build time range from preset
  const timeRange = useMemo(() => {
    if (timePreset === 'custom' && customRange) {
      return {
        start: customRange[0].toISOString(),
        end: customRange[1].toISOString(),
      }
    }
    const now = dayjs()
    let start: dayjs.Dayjs
    switch (timePreset) {
      case '1h':
        start = now.subtract(1, 'hour')
        break
      case '7d':
        start = now.subtract(7, 'day')
        break
      default:
        start = now.subtract(24, 'hour')
    }
    return { start: start.toISOString(), end: now.toISOString() }
  }, [timePreset, customRange])

  // Build query filters
  const queryFilters: LogQueryRequest = useMemo(
    () => ({
      sources:
        selectedSources.length > 0 ? selectedSources : undefined,
      levels:
        selectedLevels.length > 0 ? selectedLevels : undefined,
      time_range: timeRange,
      search: debouncedSearch || undefined,
      page,
      page_size: pageSize,
    }),
    [
      selectedSources,
      selectedLevels,
      timeRange,
      debouncedSearch,
      page,
      pageSize,
    ]
  )

  const { data: sourcesData, isLoading: sourcesLoading } =
    useLogSources()
  const { data: queryData, isLoading: queryLoading } =
    useLogQuery(queryFilters)

  return (
    <div className="log-center">
      {/* Left sidebar */}
      <div className="log-center-sidebar">
        {/* Source filter */}
        <div>
          <h3>日志源</h3>
          <Checkbox.Group
            options={SOURCE_OPTIONS}
            value={selectedSources}
            onChange={(vals) => {
              setSelectedSources(vals as string[])
              setPage(1)
            }}
          />
        </div>

        <Divider />

        {/* Level filter */}
        <div>
          <h3>级别</h3>
          <Checkbox.Group
            options={LEVEL_OPTIONS}
            value={selectedLevels}
            onChange={(vals) => {
              setSelectedLevels(vals as string[])
              setPage(1)
            }}
          />
        </div>

        <Divider />

        {/* Time range */}
        <div>
          <h3>时间范围</h3>
          <Radio.Group
            value={timePreset}
            onChange={(e) => {
              setTimePreset(e.target.value)
              setPage(1)
            }}
          >
            {TIME_PRESETS.map((p) => (
              <Radio key={p.value} value={p.value}>
                {p.label}
              </Radio>
            ))}
          </Radio.Group>
          {timePreset === 'custom' && (
            <div style={{ marginTop: 8 }}>
              <RangePicker
                showTime
                style={{ width: '100%' }}
                onChange={(dates) => {
                  setCustomRange(
                    dates as [dayjs.Dayjs, dayjs.Dayjs] | null
                  )
                  setPage(1)
                }}
              />
            </div>
          )}
        </div>

        <Divider />

        {/* Source stats */}
        <div>
          <h3>统计</h3>
          {sourcesLoading ? (
            <Spin size="small" />
          ) : (
            sourcesData?.sources.map((s) => (
              <div key={s.key} className="source-stat">
                <span>{s.label}</span>
                <span className="count">
                  {s.count.toLocaleString()}
                </span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Main area */}
      <div className="log-center-main">
        {/* Toolbar */}
        <div className="log-toolbar">
          <Input
            placeholder="搜索日志内容..."
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={handleSearchChange}
            allowClear
            style={{ width: 400 }}
          />
          <span
            style={{
              color: '#999',
              fontSize: 12,
              marginLeft: 'auto',
            }}
          >
            {queryData
              ? `${queryData.total.toLocaleString()} 条结果`
              : ''}
          </span>
        </div>

        {/* Log list */}
        <div className="log-list-container">
          {queryLoading && !queryData ? (
            <div style={{ textAlign: 'center', padding: 48 }}>
              <Spin size="large" />
            </div>
          ) : queryData && queryData.entries.length > 0 ? (
            queryData.entries.map((entry) => (
              <LogEntryRow key={entry.id} entry={entry} />
            ))
          ) : (
            <div className="log-list-empty">
              {queryLoading ? '加载中...' : '暂无匹配的日志'}
            </div>
          )}
        </div>

        {/* Pagination */}
        {queryData && queryData.total > 0 && (
          <div className="log-pagination">
            <Pagination
              current={page}
              pageSize={pageSize}
              total={queryData.total}
              showSizeChanger
              showQuickJumper
              pageSizeOptions={['20', '50', '100', '200']}
              showTotal={(total) => `共 ${total} 条`}
              onChange={(p, ps) => {
                setPage(p)
                setPageSize(ps)
              }}
            />
          </div>
        )}
      </div>
    </div>
  )
}

export default LogCenter
