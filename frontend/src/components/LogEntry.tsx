import { useState } from 'react'
import { Tag, Button, Typography, Space } from 'antd'
import {
  CopyOutlined,
  DownOutlined,
  RightOutlined,
} from '@ant-design/icons'
import type { LogEntry as LogEntryType } from '../services/logs'
import dayjs from 'dayjs'

const { Text } = Typography

const LEVEL_COLORS: Record<string, string> = {
  error: 'red',
  warning: 'orange',
  info: 'blue',
  debug: 'default',
}

const SOURCE_LABELS: Record<string, string> = {
  claude_cli: 'CLI',
  failure_analysis: '分析',
  app: '应用',
  scheduler: '调度',
}

const SOURCE_COLORS: Record<string, string> = {
  claude_cli: 'purple',
  failure_analysis: 'green',
  app: 'cyan',
  scheduler: 'geekblue',
}

interface Props {
  entry: LogEntryType
}

function LogEntryRow({ entry }: Props) {
  const [expanded, setExpanded] = useState(false)

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation()
    navigator.clipboard.writeText(entry.content).catch(() => {
      // ignore clipboard errors
    })
  }

  return (
    <div
      style={{
        borderBottom: '1px solid #f0f0f0',
        cursor: 'pointer',
        transition: 'background 0.15s',
      }}
      onClick={() => setExpanded(!expanded)}
      onMouseEnter={(e) => {
        ;(e.currentTarget as HTMLElement).style.background = '#fafafa'
      }}
      onMouseLeave={(e) => {
        ;(e.currentTarget as HTMLElement).style.background = 'transparent'
      }}
    >
      {/* Collapsed row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          padding: '8px 16px',
          gap: 12,
          fontFamily: "'Consolas', 'Monaco', 'Courier New', monospace",
          fontSize: 13,
          lineHeight: '20px',
        }}
      >
        <Text
          type="secondary"
          style={{
            whiteSpace: 'nowrap',
            minWidth: 75,
            fontSize: 12,
            fontFamily: 'inherit',
          }}
        >
          {dayjs(entry.timestamp).format('MM-DD HH:mm:ss')}
        </Text>
        <Tag
          color={LEVEL_COLORS[entry.level] || 'default'}
          style={{
            margin: 0,
            textTransform: 'uppercase',
            fontSize: 11,
          }}
        >
          {entry.level}
        </Tag>
        <Tag
          color={SOURCE_COLORS[entry.source] || 'default'}
          style={{ margin: 0, fontSize: 11 }}
        >
          {SOURCE_LABELS[entry.source] || entry.source}
        </Tag>
        <Text
          ellipsis
          style={{
            flex: 1,
            fontFamily: 'inherit',
            fontSize: 13,
          }}
        >
          {entry.summary || '(empty)'}
        </Text>
        <Space size={4}>
          <Button
            type="text"
            size="small"
            icon={<CopyOutlined />}
            onClick={handleCopy}
            style={{ opacity: 0.5 }}
          />
          {expanded ? (
            <DownOutlined style={{ fontSize: 10, opacity: 0.4 }} />
          ) : (
            <RightOutlined style={{ fontSize: 10, opacity: 0.4 }} />
          )}
        </Space>
      </div>

      {/* Expanded content */}
      {expanded && (
        <div
          style={{
            padding: '12px 16px 16px',
            background: '#f9f9f9',
            borderTop: '1px solid #eee',
          }}
        >
          {/* Metadata tags */}
          {entry.metadata &&
            Object.keys(entry.metadata).length > 0 && (
              <div
                style={{
                  marginBottom: 8,
                  display: 'flex',
                  gap: 6,
                  flexWrap: 'wrap',
                }}
              >
                {entry.metadata.provider && (
                  <Tag color="blue">{entry.metadata.provider}</Tag>
                )}
                {entry.metadata.model && (
                  <Tag color="geekblue">{entry.metadata.model}</Tag>
                )}
                {entry.metadata.workflow_name && (
                  <Tag color="green">{entry.metadata.workflow_name}</Tag>
                )}
                {entry.metadata.job_name && (
                  <Tag color="lime">{entry.metadata.job_name}</Tag>
                )}
                {entry.metadata.module && (
                  <Tag color="cyan">{entry.metadata.module}</Tag>
                )}
                {entry.metadata.duration_seconds != null && (
                  <Tag>{entry.metadata.duration_seconds.toFixed(1)}s</Tag>
                )}
                {entry.metadata.exit_code != null &&
                  entry.metadata.exit_code !== 0 && (
                    <Tag color="red">exit={entry.metadata.exit_code}</Tag>
                  )}
              </div>
            )}

          {/* Full log content */}
          <pre
            style={{
              margin: 0,
              padding: 12,
              background: '#1e1e1e',
              color: '#d4d4d4',
              borderRadius: 6,
              fontFamily:
                "'Consolas', 'Monaco', 'Courier New', monospace",
              fontSize: 12,
              lineHeight: '18px',
              maxHeight: 480,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
            }}
          >
            {entry.content}
          </pre>

          <div style={{ marginTop: 8, textAlign: 'right' }}>
            <Button
              size="small"
              icon={<CopyOutlined />}
              onClick={handleCopy}
            >
              复制全部
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

export default LogEntryRow
