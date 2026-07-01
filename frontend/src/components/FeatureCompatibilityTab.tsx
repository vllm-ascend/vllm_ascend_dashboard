import { Card, Spin, Typography, Tag, Tooltip, Empty, Space } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { getFeatureCompatibility } from '../services/models'
import type { FeatureCompatEntry } from '../types/models'
import dayjs from 'dayjs'

const { Text, Title } = Typography

const COMPAT_COLORS: Record<string, string> = {
  full: '#52c41a',
  partial: '#faad14',
  none: '#ff4d4f',
  unknown: '#d9d9d9',
}

const COMPAT_SYMBOLS: Record<string, string> = {
  full: '✅',
  partial: '🟠',
  none: '❌',
  unknown: '❔',
}

export default function FeatureCompatibilityTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['feature-compatibility'],
    queryFn: getFeatureCompatibility,
  })

  if (isLoading) {
    return <Card><Spin /></Card>
  }

  const features = data?.features || []
  const matrix = data?.matrix || []

  if (features.length === 0) {
    return (
      <Card>
        <Empty description="暂无特性互操作数据，请先执行上游同步" />
      </Card>
    )
  }

  const compatMap: Record<string, Record<string, FeatureCompatEntry>> = {}
  for (const entry of matrix) {
    if (!compatMap[entry.feature_a]) compatMap[entry.feature_a] = {}
    compatMap[entry.feature_a][entry.feature_b] = entry
    if (!compatMap[entry.feature_b]) compatMap[entry.feature_b] = {}
    compatMap[entry.feature_b][entry.feature_a] = entry
  }

  const cellSize = 36
  const labelWidth = 140
  const headerHeight = 100

  return (
    <div>
      <Card style={{ marginBottom: 12 }}>
        <Space size="large" wrap>
          {data?.legend && Object.entries(data.legend).map(([key, label]) => (
            <Tag key={key} style={{ fontSize: '13px' }}>
              <span style={{ color: COMPAT_COLORS[key] }}>{COMPAT_SYMBOLS[key]}</span> {label}
            </Tag>
          ))}
          {data?.synced_at && (
            <Text type="secondary">
              同步时间: {dayjs(data.synced_at).add(8, 'hour').format('YYYY-MM-DD HH:mm')}
            </Text>
          )}
        </Space>
      </Card>

      <Card title="Feature × Feature 互操作矩阵" styles={{ body: { overflowX: 'auto' } }}>
        <div style={{ minWidth: labelWidth + features.length * cellSize + 20 }}>
          {/* Header row */}
          <div style={{ display: 'flex', height: headerHeight, marginBottom: 4 }}>
            <div style={{ width: labelWidth, flexShrink: 0 }} />
            {features.map((feat) => (
              <div
                key={feat}
                style={{
                  width: cellSize,
                  flexShrink: 0,
                  display: 'flex',
                  alignItems: 'flex-end',
                  justifyContent: 'center',
                  transform: 'rotate(-60deg) translateY(20px)',
                  transformOrigin: 'bottom center',
                  fontSize: '11px',
                  whiteSpace: 'nowrap',
                  color: '#666',
                }}
              >
                {feat}
              </div>
            ))}
          </div>

          {/* Matrix rows */}
          {features.map((rowFeat) => (
            <div key={rowFeat} style={{ display: 'flex', height: cellSize, alignItems: 'center' }}>
              <div
                style={{
                  width: labelWidth,
                  flexShrink: 0,
                  fontSize: '12px',
                  textAlign: 'right',
                  paddingRight: '8px',
                  color: '#333',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
                title={rowFeat}
              >
                {rowFeat}
              </div>
              {features.map((colFeat) => {
                const entry = compatMap[rowFeat]?.[colFeat]
                const isDiagonal = rowFeat === colFeat
                const compat = entry?.compatibility || 'unknown'

                if (isDiagonal) {
                  return (
                    <div
                      key={colFeat}
                      style={{
                        width: cellSize,
                        height: cellSize - 2,
                        flexShrink: 0,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        backgroundColor: '#f0f0f0',
                        border: '1px solid #fff',
                        fontSize: '14px',
                      }}
                    >
                      ✅
                    </div>
                  )
                }

                return (
                  <Tooltip
                    key={colFeat}
                    title={
                      <div>
                        <div>{rowFeat} × {colFeat}</div>
                        <div>{COMPAT_SYMBOLS[compat]} {compat}</div>
                        {entry?.footnote && <div style={{ marginTop: 4, color: '#faad14' }}>{entry.footnote}</div>}
                      </div>
                    }
                  >
                    <div
                      style={{
                        width: cellSize,
                        height: cellSize - 2,
                        flexShrink: 0,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        backgroundColor: COMPAT_COLORS[compat],
                        border: '1px solid #fff',
                        cursor: 'pointer',
                        fontSize: '14px',
                        borderRadius: '2px',
                      }}
                    >
                      {COMPAT_SYMBOLS[compat]}
                    </div>
                  </Tooltip>
                )
              })}
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
