import { Drawer, Spin, Alert, Button, Space, Tag, Typography, Tooltip } from 'antd'
import { LinkOutlined, GithubOutlined } from '@ant-design/icons'
import { useCoverageSource } from '../../hooks/useTestBoard'
import type { CoverageSourceData } from '../../services/testBoard'

const { Text } = Typography

interface Props {
  path: string | null
  commit: string | null
  onClose: () => void
}

/** 逐行覆盖染色：绿=完全覆盖 / 琥珀=partial分支 / 红=未执行 / 灰=排除 */
function lineClass(
  lineNo: number,
  executed: Set<number>,
  missing: Set<number>,
  excluded: Set<number>,
  partialFrom: Set<number>,
): { bg: string; label?: string } {
  if (excluded.has(lineNo)) return { bg: '#f0f0f0' }
  if (missing.has(lineNo)) return { bg: '#fff1f0' }
  if (executed.has(lineNo)) {
    if (partialFrom.has(lineNo)) return { bg: '#fff7e6', label: 'partial' }
    return { bg: '#f6ffed' }
  }
  return { bg: 'transparent' }
}

export default function CoverageCodeViewer({ path, commit, onClose }: Props) {
  const { data, isLoading, error } = useCoverageSource(path) as {
    data: CoverageSourceData | null; isLoading: boolean; error: unknown
  }

  const lines = data ? data.source.split('\n') : []
  const executed = new Set(data?.executed_lines ?? [])
  const missing = new Set(data?.missing_lines ?? [])
  const excluded = new Set(data?.excluded_lines ?? [])
  const partialFrom = new Set((data?.missing_branches ?? []).map((b) => b[0]))

  // 缺失分支按源行分组（标注 partial 行右侧）
  const missingBranchByLine: Record<number, Array<[number, number]>> = {}
  ;(data?.missing_branches ?? []).forEach((b) => {
    const [from, to] = b
    ;(missingBranchByLine[from] = missingBranchByLine[from] || []).push([from, to])
  })

  const percent = data?.summary?.percent_covered ?? 0
  const linePct = data?.summary?.percent_statements_covered ?? percent
  const branchPct = data?.summary?.percent_branches_covered

  return (
    <Drawer
      title={path ? `覆盖详情：${path}` : '覆盖详情'}
      open={!!path}
      onClose={onClose}
      width="70%"
      destroyOnClose
      extra={
        data?.github_url ? (
          <Button type="link" href={data.github_url} target="_blank" icon={<GithubOutlined />}>
            在 GitHub 查看
          </Button>
        ) : null
      }
    >
      {isLoading && <Spin tip="加载源码与覆盖数据..." />}
      {error ? <Alert type="error" message="加载失败" description={String(error)} /> : null}
      {data && (
        <>
          {!data.source_aligned && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message="源码版本对齐提示"
              description="未能取到 covdata 对应 commit 的源码，已回退 HEAD 版本，行号可能错位。"
            />
          )}
          <Space wrap style={{ marginBottom: 12 }}>
            <Tag color="blue">commit {(data.commit || '?').slice(0, 7)}</Tag>
            <Tag color={percent >= 80 ? 'green' : percent >= 50 ? 'gold' : 'red'}>覆盖率 {percent.toFixed(1)}%</Tag>
            <Tag>行覆盖率 {linePct.toFixed(1)}%</Tag>
            {branchPct !== undefined && <Tag>分支覆盖率 {branchPct.toFixed(1)}%</Tag>
            }
            <Text type="secondary" style={{ fontSize: 12 }}>
              statements {data.summary.num_statements ?? 0} · missing {data.summary.missing_lines ?? 0}
            </Text>
          </Space>

          <div style={{ marginBottom: 8, fontSize: 12 }}>
            <Space size={16}>
              <span><span style={{ display: 'inline-block', width: 14, height: 14, background: '#f6ffed', marginRight: 4, border: '1px solid #d9f7be' }} />已覆盖</span>
              <span><span style={{ display: 'inline-block', width: 14, height: 14, background: '#fff7e6', marginRight: 4, border: '1px solid #ffe58f' }} />partial 分支</span>
              <span><span style={{ display: 'inline-block', width: 14, height: 14, background: '#fff1f0', marginRight: 4, border: '1px solid #ffa39e' }} />未执行</span>
              <span><span style={{ display: 'inline-block', width: 14, height: 14, background: '#f0f0f0', marginRight: 4, border: '1px solid #d9d9d9' }} />排除</span>
            </Space>
          </div>

          <div
            style={{
              fontFamily: "'SF Mono', Menlo, Consolas, monospace",
              fontSize: 13,
              lineHeight: '20px',
              background: '#fafafa',
              border: '1px solid #f0f0f0',
              maxHeight: '70vh',
              overflow: 'auto',
            }}
          >
            {lines.map((code, i) => {
              const lineNo = i + 1
              const cls = lineClass(lineNo, executed, missing, excluded, partialFrom)
              const branches = missingBranchByLine[lineNo]
              return (
                <div key={lineNo} style={{ display: 'flex', background: cls.bg }}>
                  <span style={{ width: 48, flexShrink: 0, textAlign: 'right', paddingRight: 8, color: '#999', userSelect: 'none' }}>
                    {lineNo}
                  </span>
                  <span style={{ whiteSpace: 'pre', flex: 1, paddingLeft: 8, overflowX: 'auto' }}>
                    {code || ' '}
                  </span>
                  {branches && (
                    <Tooltip title={branches.map((b) => `→ ${b[1]}`).join(', ')}>
                      <span style={{ color: '#ad6800', fontSize: 11, paddingRight: 8, whiteSpace: 'nowrap' }}>!</span>
                    </Tooltip>
                  )}
                </div>
              )
            })}
          </div>
          <div style={{ marginTop: 8 }}>
            <Button type="link" icon={<LinkOutlined />} href={data.github_url || '#'} target="_blank" disabled={!data.github_url}>
              GitHub 源码
            </Button>
          </div>
        </>
      )}
    </Drawer>
  )
}
