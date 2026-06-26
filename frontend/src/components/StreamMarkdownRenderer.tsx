import React, { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface DiagnosisSummary {
  total_content_length: number
  duration_seconds: number
  chunk_count: number
}

interface StreamMarkdownRendererProps {
  content: string
  isStreaming: boolean
  meta?: { provider: string; model: string } | null
  summary?: DiagnosisSummary | null
}

export type { DiagnosisSummary }

const StreamMarkdownRenderer: React.FC<StreamMarkdownRendererProps> = ({
  content,
  isStreaming,
  meta,
  summary,
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const [shouldAutoScroll, setShouldAutoScroll] = useState(true)

  useEffect(() => {
    if (shouldAutoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [content, shouldAutoScroll])

  const handleScroll = () => {
    if (!containerRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 100
    setShouldAutoScroll(isNearBottom)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {(meta || summary || isStreaming) && (
        <div style={{
          padding: '8px 12px',
          background: '#f0f0f0',
          borderRadius: '4px',
          marginBottom: 8,
          fontSize: 12,
          color: '#666',
          display: 'flex',
          justifyContent: 'space-between',
        }}>
          {meta && (
            <span>
              模型: {meta.provider}/{meta.model}
            </span>
          )}
          {summary && (
            <span>
              耗时: {summary.duration_seconds}s | 输出: {summary.total_content_length}字符
            </span>
          )}
          {isStreaming && !summary && (
            <span style={{ color: '#1890ff' }}>生成中...</span>
          )}
        </div>
      )}

      <div
        ref={containerRef}
        onScroll={handleScroll}
        style={{
          flex: 1,
          padding: 16,
          background: '#fafafa',
          borderRadius: 8,
          overflowY: 'auto',
          minHeight: 200,
        }}
      >
        {content ? (
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              table: ({ node, ...props }) => (
                <div style={{ overflowX: 'auto', marginBottom: 16 }}>
                  <table style={{ borderCollapse: 'collapse', width: '100%' }} {...props} />
                </div>
              ),
              th: ({ node, ...props }) => (
                <th style={{ border: '1px solid #d9d9d9', padding: '8px 12px', background: '#f5f5f5', textAlign: 'left' }} {...props} />
              ),
              td: ({ node, ...props }) => (
                <td style={{ border: '1px solid #d9d9d9', padding: '8px 12px', verticalAlign: 'top' }} {...props} />
              ),
            }}
          >
            {content}
          </ReactMarkdown>
        ) : (
          <div style={{ textAlign: 'center', padding: 40, color: '#8c8c8c' }}>
            {isStreaming ? '正在生成分析结果...' : '点击"开始诊断"按钮进行问题定位'}
          </div>
        )}
        {isStreaming && (
          <span style={{ color: '#1890ff', fontWeight: 'bold' }}>▊</span>
        )}
      </div>
    </div>
  )
}

export default StreamMarkdownRenderer
