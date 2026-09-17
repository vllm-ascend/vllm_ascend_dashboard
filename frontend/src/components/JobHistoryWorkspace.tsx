import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Collapse, Empty, Modal, Space, Spin, Table, Tag, Typography, message } from 'antd'
import { CopyOutlined, GithubOutlined, RobotOutlined } from '@ant-design/icons'
import api from '../services/api'
import { createJobLogRootCause, getJobComparison, getJobLogRootCause, refreshRunVersionSnapshot } from '../services/ci'
import type { CIJob, FailureStageEvidence } from '../services/ci'
import { formatDuration } from '../utils/ciRenderers'
import { formatTimezone } from '../utils/timezone'

const { Text, Link } = Typography

function TimelineNode({
  record, currentJobId, selectedAsStart, selectedAsEnd, onStart, onEnd, onOpenSummary, versionProbeRunning,
}: {
  record: CIJob
  currentJobId: number
  selectedAsStart: boolean
  selectedAsEnd: boolean
  onStart: () => void
  onEnd: () => void
  onOpenSummary?: (jobId: number) => void
  versionProbeRunning?: boolean
}) {
  const [hovered, setHovered] = useState(false)
  const failedStep = record.steps_summary?.find(step => ['failure', 'timed_out', 'cancelled'].includes(step.conclusion || ''))?.name
  const nodeColor = record.conclusion === 'success' ? '#237a45' : record.conclusion === 'failure' ? '#b8323c' : '#595959'
  const statusText = record.conclusion === 'success' ? '成功' : record.conclusion === 'failure' ? '失败' : record.conclusion || '未知'

  return (
    <div style={{ width: 190, flex: '0 0 190px', position: 'relative', textAlign: 'center' }}>
      <div style={{ height: 28, color: '#595959', fontSize: 12 }}>{record.started_at ? formatTimezone(record.started_at, 'MM-DD') : '时间未知'}</div>
      <div style={{ height: 50, display: 'flex', justifyContent: 'center' }}>
        <a
          href={record.github_job_url}
          target="_blank"
          rel="noopener noreferrer"
          title="打开 GitHub Job 日志"
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          style={{
            width: 76,
            height: 36,
            lineHeight: '32px',
            background: nodeColor,
            color: '#fff',
            border: `2px solid ${nodeColor}`,
            borderRadius: 2,
            fontWeight: 700,
            fontSize: 13,
            zIndex: 1,
            boxShadow: selectedAsStart || selectedAsEnd ? '0 0 0 2px #262626' : undefined,
            textDecoration: 'none',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: hovered ? 5 : 0,
            transition: 'gap 160ms ease, transform 160ms ease, filter 160ms ease',
            transform: hovered ? 'translateY(-2px)' : 'none',
            filter: hovered ? 'brightness(1.08)' : 'none',
          }}
        >
          <GithubOutlined style={{ width: hovered ? 15 : 0, opacity: hovered ? 1 : 0, overflow: 'hidden', transition: 'width 160ms ease, opacity 120ms ease' }} />
          <span>{statusText}</span>
        </a>
      </div>
      <div style={{ fontSize: 12, fontWeight: 600 }}>{record.started_at ? formatTimezone(record.started_at, 'HH:mm') : '--:--'}</div>
      <div style={{ color: '#595959', fontSize: 12, marginTop: 2 }}>{formatDuration(record.duration_seconds)}</div>
      <div style={{ height: 18, marginTop: 2, fontSize: 11 }}>
        {record.vllm_ascend_commit ? (
          <Link
            href={`https://github.com/vllm-project/vllm-ascend/commit/${record.vllm_ascend_commit}`}
            target="_blank"
            title={record.vllm_ascend_commit}
          >
            commit {record.vllm_ascend_commit.slice(0, 7)}
          </Link>
        ) : <Text type="secondary">{versionProbeRunning ? '自动勘测中…' : '版本未知'}</Text>}
      </div>
      <div title={record.vllm_ascend_commit_message || undefined} style={{ height: 17, color: '#595959', fontSize: 10 }}>
        {record.vllm_ascend_commit_date ? `版本 ${formatTimezone(record.vllm_ascend_commit_date, 'MM-DD HH:mm')}` : '版本时间未知'}
      </div>
      <div title={failedStep || undefined} style={{ height: 36, marginTop: 3, padding: '0 5px', color: record.conclusion === 'success' ? '#8c8c8c' : '#a61d24', fontSize: 11, lineHeight: '17px', overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
        {record.conclusion === 'success' ? '—' : `失败阶段：${failedStep || '未识别'}`}
      </div>
      <div style={{ height: 24 }}>
        {record.conclusion !== 'success' && onOpenSummary && (
          <Button type="link" size="small" icon={<RobotOutlined />} onClick={() => onOpenSummary(record.job_id)} style={{ height: 22, padding: 0, fontSize: 12 }}>
            日志根因摘要
          </Button>
        )}
      </div>
      {record.job_id === currentJobId && <Tag style={{ margin: '4px 0 0' }}>当前</Tag>}
      <Space size={4} style={{ marginTop: 6 }}>
        <Button size="small" type={selectedAsStart ? 'primary' : 'default'} style={{ borderRadius: 2, paddingInline: 7 }} onClick={onStart}>Start</Button>
        <Button size="small" type={selectedAsEnd ? 'primary' : 'default'} style={{ borderRadius: 2, paddingInline: 7 }} onClick={onEnd}>End</Button>
      </Space>
    </div>
  )
}

function displayValue(value: unknown) {
  if (value === null || value === undefined || value === '') return <Text type="secondary">未知</Text>
  if (Array.isArray(value)) return value.length ? value.join(', ') : <Text type="secondary">空</Text>
  return String(value)
}

export function JobHistoryWorkspace({ job }: { job: CIJob }) {
  const [startJobId, setStartJobId] = useState<number | null>(null)
  const [endJobId, setEndJobId] = useState<number | null>(null)
  const [summaryJobId, setSummaryJobId] = useState<number | null>(null)
  const [probingRunIds, setProbingRunIds] = useState<Set<number>>(new Set())
  const attemptedVersionRuns = useRef(new Set<number>())
  const queryClient = useQueryClient()
  const storedSummary = useQuery({
    queryKey: ['job-log-root-cause', summaryJobId],
    queryFn: () => getJobLogRootCause(summaryJobId!),
    enabled: Boolean(summaryJobId),
  })
  const createSummary = useMutation({
    mutationFn: () => createJobLogRootCause(
      summaryJobId!,
      storedSummary.data?.status === 'completed',
    ),
    onSuccess: data => {
      queryClient.setQueryData(['job-log-root-cause', summaryJobId], data)
      if (data.status === 'completed') message.success('日志根因摘要已生成并永久保存')
      else message.error(data.error_message || '摘要生成失败')
    },
    onError: (error: any) => message.error(error?.response?.data?.detail || '摘要生成失败'),
  })
  const { data = [], isLoading, isError } = useQuery<CIJob[]>({
    queryKey: ['inline-job-history', job.workflow_name, job.job_name],
    queryFn: async () => (await api.get<CIJob[]>('/job-owners/jobs/runs', {
      params: { workflow_name: job.workflow_name, job_name: job.job_name, limit: 500, official_only: true },
    })).data,
  })

  useEffect(() => {
    const runIds = [...new Set(
      data
        .filter(record => !record.vllm_ascend_commit && !attemptedVersionRuns.current.has(record.run_id))
        .map(record => record.run_id),
    )]
    if (runIds.length === 0) return
    runIds.forEach(runId => attemptedVersionRuns.current.add(runId))
    let cancelled = false
    setProbingRunIds(new Set(runIds))
    void (async () => {
      let collected = false
      for (const runId of runIds) {
        if (cancelled) break
        try {
          await refreshRunVersionSnapshot(runId)
          collected = true
        } catch {
          // Missing/expired logs are represented as "版本未知"; do not turn
          // automatic evidence collection into a page-level error.
        } finally {
          if (!cancelled) {
            setProbingRunIds(previous => {
              const next = new Set(previous)
              next.delete(runId)
              return next
            })
          }
        }
      }
      if (!cancelled && collected) {
        await queryClient.invalidateQueries({ queryKey: ['inline-job-history', job.workflow_name, job.job_name] })
        await queryClient.invalidateQueries({ queryKey: ['job-comparison'] })
      }
    })()
    return () => { cancelled = true }
  }, [data, job.job_name, job.workflow_name, queryClient])

  const start = data.find(item => item.job_id === startJobId)
  const end = data.find(item => item.job_id === endJobId)
  const timeline = [...data].sort((a, b) => new Date(a.started_at || 0).getTime() - new Date(b.started_at || 0).getTime())
  const intervalInvalid = Boolean(start?.started_at && end?.started_at && new Date(start.started_at) >= new Date(end.started_at))
  const canCompare = Boolean(startJobId && endJobId && !intervalInvalid)
  const comparison = useQuery({
    queryKey: ['job-comparison', startJobId, endJobId],
    queryFn: () => getJobComparison(startJobId!, endJobId!),
    enabled: canCompare,
  })
  const intervalRecords = canCompare && start?.started_at && end?.started_at
    ? timeline.filter(record => {
        const timestamp = new Date(record.started_at || 0).getTime()
        return timestamp >= new Date(start.started_at!).getTime()
          && timestamp <= new Date(end.started_at!).getTime()
      })
    : []
  const intervalLogSummaries = useQuery({
    queryKey: ['interval-log-summaries', startJobId, endJobId, intervalRecords.map(item => item.job_id)],
    queryFn: async () => {
      const summaries = []
      // Fetch sequentially to avoid a burst of GitHub log-download requests.
      for (const record of intervalRecords) {
        if (record.conclusion === 'success') {
          summaries.push({ record, summary: '运行成功，未发现失败日志。', source: 'status' })
          continue
        }
        try {
          const evidence = await getJobLogRootCause(record.job_id)
          summaries.push({
            record,
            summary: evidence?.status === 'completed' && evidence.summary
              ? evidence.summary
              : '尚未生成日志根因摘要，请点击该节点的“日志根因摘要”生成。',
            source: evidence?.status === 'completed'
              ? `${evidence.llm_provider || 'LLM'}/${evidence.llm_model || '未知模型'}`
              : '未生成',
          })
        } catch {
          summaries.push({ record, summary: '日志不可用或已过期', source: 'unavailable' })
        }
      }
      return summaries
    },
    enabled: canCompare && intervalRecords.length > 0,
  })

  const copyComparisonEvidence = async () => {
    if (!comparison.data || !start || !end) return
    const evidence = comparison.data
    const versionLine = (label: string, side: 'start' | 'end') => {
      const snapshot = evidence[side]
      const sha = snapshot.vllm_ascend_commit || '未知'
      return `- ${label}: ${sha}${snapshot.vllm_ascend_commit_date ? ` (${snapshot.vllm_ascend_commit_date})` : ''}${snapshot.vllm_ascend_commit ? `\n  https://github.com/vllm-project/vllm-ascend/commit/${snapshot.vllm_ascend_commit}` : ''}`
    }
    const prLines = [...evidence.pr_changes.items]
      .sort((a, b) => new Date(a.merged_at || 0).getTime() - new Date(b.merged_at || 0).getTime())
      .map(item => `- ${item.merged_at ? formatTimezone(item.merged_at) : '合入时间未知'} | ${item.number ? `PR #${item.number}` : item.sha?.slice(0, 7)} | ${item.title}${item.author ? ` | ${item.author}` : ''}${item.url ? `\n  ${item.url}` : ''}`)
    const revertLines = (evidence.pr_changes.revert_commits || []).map(item =>
      `- ${item.revert_pr ? `PR #${item.revert_pr}` : '回退提交'} 回退 PR #${item.reverted_pr} | ${item.cancellation_status === 'cancelled' ? '双方均在区间内，已抵消' : '仅单方在区间内，不抵消'}${item.url ? `\n  ${item.url}` : ''}`,
    )
    const linkLines = intervalRecords.map(record => `- ${formatTimezone(record.started_at)} | ${record.conclusion || '未知'} | ${record.github_job_url || '无链接'}`)
    const logLines = (intervalLogSummaries.data || []).map(({ record, summary, source }) => `- ${formatTimezone(record.started_at)} | ${record.conclusion || '未知'} | ${source}\n  ${summary}`)
    const stageLine = (label: string, stage: FailureStageEvidence | undefined) => `- ${label}: ${stage?.first_failed_step || '未知'}；${stage?.direct_error || '无直接错误信息'}`
    const text = [
      `故障定位证据：${job.job_name}`,
      `区间：${formatTimezone(start.started_at)} -> ${formatTimezone(end.started_at)}`,
      '',
      '【区间链接】',
      ...(linkLines.length ? linkLines : ['- 无']),
      '',
      '【vllm-ascend 版本】',
      versionLine('Start', 'start'),
      versionLine('End', 'end'),
      '',
      '【PR 合入时间线】',
      ...(prLines.length ? prLines : ['- 区间内无有效 PR']),
      evidence.pr_changes.compare_url ? `- GitHub commit 对比：${evidence.pr_changes.compare_url}` : '',
      ...(revertLines.length ? ['', '【回退关系】', ...revertLines] : []),
      '',
      '【失败阶段差异】',
      stageLine('Start', evidence.failure_stage_difference.start),
      stageLine('End', evidence.failure_stage_difference.end),
      '',
      '【区间日志汇总】',
      ...(logLines.length ? logLines : ['- 尚无日志汇总']),
    ].join('\n')
    try {
      await navigator.clipboard.writeText(text)
      message.success('故障定位证据已复制到剪贴板')
    } catch {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      const copied = document.execCommand('copy')
      document.body.removeChild(textarea)
      copied ? message.success('故障定位证据已复制到剪贴板') : message.error('复制失败，请检查浏览器剪贴板权限')
    }
  }

  const stageCard = (label: string, stage: FailureStageEvidence | undefined) => (
    <div style={{ flex: 1, minWidth: 220, border: '1px solid #d9d9d9', padding: '8px 10px' }}>
      <Text strong>{label}</Text>
      <div>首个失败阶段：{displayValue(stage?.first_failed_step)}</div>
      <div>直接报错点：{displayValue(stage?.direct_error)}</div>
    </div>
  )
  const revertRelations = comparison.data?.pr_changes.revert_commits || []
  const cancelledRelationCount = revertRelations.filter(item => item.cancellation_status === 'cancelled').length
  const retainedRelationCount = revertRelations.length - cancelledRelationCount

  return (
    <Card size="small" title={`Job 运行历史 · ${job.job_name}`} style={{ margin: '8px 0' }}>
      <Text type="secondary">以首页“今日 CI 详情”中的 Workflow/Job 集合作为范围，向历史回溯并展示每天对应的正式运行；不是只展示今天的 Run。选择较早记录为 Start、较新记录为 End。</Text>
      {(start || end) && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, margin: '10px 0' }}>
          {[{ label: 'Start', item: start }, { label: 'End', item: end }].map(({ label, item }) => (
            <div key={label} style={{ border: '1px solid #8c8c8c', padding: '7px 10px', background: '#fafafa' }}>
              <strong style={{ marginRight: 10 }}>{label}</strong>{item ? formatTimezone(item.started_at) : '未选择'}
            </div>
          ))}
        </div>
      )}
      {intervalInvalid && <Alert type="warning" showIcon message="Start 必须早于 End，请重新选择边界。" style={{ marginTop: 10 }} />}
      {isError && <Alert type="error" showIcon message="历史记录加载失败" style={{ marginTop: 10 }} />}
      {!isLoading && !isError && !data.some(item => item.job_id === job.job_id) && (
        <Alert type="info" showIcon message="当前 Job 不属于首页 CI 配置定义的正式运行，因此未加入时间线。" style={{ marginTop: 10 }} />
      )}
      {isLoading ? <div style={{ padding: 40, textAlign: 'center' }}><Spin /></div> : timeline.length === 0 ? (
        <Empty description="暂无同名 Job 历史记录" />
      ) : (
        <div style={{ overflowX: 'auto', padding: '14px 4px 10px' }}>
          <div style={{ display: 'flex', minWidth: 'max-content', position: 'relative', gap: 8 }}>
            <div style={{ position: 'absolute', left: 48, right: 48, top: 53, height: 1, background: '#8c8c8c' }} />
            {timeline.map(record => {
              const selectedAsStart = startJobId === record.job_id
              const selectedAsEnd = endJobId === record.job_id
              return (
                <TimelineNode
                  key={record.job_id}
                  record={record}
                  currentJobId={job.job_id}
                  selectedAsStart={selectedAsStart}
                  selectedAsEnd={selectedAsEnd}
                  onStart={() => { setStartJobId(record.job_id); if (endJobId === record.job_id) setEndJobId(null) }}
                  onEnd={() => { setEndJobId(record.job_id); if (startJobId === record.job_id) setStartJobId(null) }}
                  onOpenSummary={setSummaryJobId}
                  versionProbeRunning={probingRunIds.has(record.run_id)}
                />
              )
            })}
          </div>
        </div>
      )}

      {canCompare && comparison.isLoading && (
        <div style={{ padding: 24, textAlign: 'center' }}>
          <Spin tip="正在获取 PR 证据链，请稍候…" size="large" />
          <div style={{ marginTop: 34 }}><Text type="secondary">PR 较多时需要从 GitHub 分批获取合入时间和详情，请不要重复点击 Start / End。</Text></div>
        </div>
      )}
      {canCompare && comparison.isError && <Alert type="error" showIcon message="差异证据加载失败，请检查后端日志。" />}
      {comparison.data && (
        <div style={{ marginTop: 12 }}>
          <Alert type="info" showIcon message="展示实际 vllm-ascend commit 区间内的合入 PR 全集" description={comparison.data.warnings.join('；')} style={{ marginBottom: 8 }} />
          <Button type="primary" icon={<CopyOutlined />} loading={intervalLogSummaries.isLoading} onClick={copyComparisonEvidence} style={{ marginBottom: 8 }}>一键复制全部故障定位证据</Button>
          <Collapse size="small" defaultActiveKey={['commit', 'pr', 'stage']} items={[
            {
              key: 'commit',
              label: 'CI 实际对应的 vllm-ascend commit 版本',
              children: <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                {(['start', 'end'] as const).map(side => {
                  const sha = comparison.data?.[side].vllm_ascend_commit
                  return <div key={side} style={{ border: '1px solid #d9d9d9', padding: '8px 10px' }}>
                    <Text strong>{side === 'start' ? 'Start' : 'End'}：</Text>
                    {sha ? <><Link href={`https://github.com/vllm-project/vllm-ascend/commit/${sha}`} target="_blank"><code>{sha}</code></Link><div><Text type="secondary">提交时间：{displayValue(comparison.data?.[side].vllm_ascend_commit_date)}</Text></div></> : <Text type="secondary">未知（不会使用 Workflow head SHA 代替）</Text>}
                  </div>
                })}
              </div>,
            },
            { key: 'pr', label: `PR / 提交修改（${comparison.data.pr_changes.items.length} 个）`, children: <>
              {comparison.data.pr_changes.compare_url && <div style={{ marginBottom: 8 }}><Link href={comparison.data.pr_changes.compare_url} target="_blank">打开 GitHub commit 对比</Link></div>}
              {comparison.data.pr_changes.error && <Alert type="warning" showIcon message={`GitHub compare 获取失败：${comparison.data.pr_changes.error}`} style={{ marginBottom: 8 }} />}
              {comparison.data.pr_changes.items.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Start / End 的 commit 范围内没有提交，或 compare 暂不可用" /> :
                <div style={{ width: 'min(100%, 980px)' }}>
                  <Table size="small" pagination={false} tableLayout="fixed" rowKey={row => row.sha || String(row.number)} dataSource={[...comparison.data.pr_changes.items].sort((a, b) => new Date(a.merged_at || 0).getTime() - new Date(b.merged_at || 0).getTime())} columns={[
                    { title: '', width: 34, render: () => <div style={{ position: 'relative', height: 36, borderLeft: '2px solid #64748b', marginLeft: 8 }}><span style={{ position: 'absolute', top: 12, left: -6, width: 10, height: 10, background: '#334155', border: '2px solid #fff', boxShadow: '0 0 0 1px #334155' }} /></div> },
                    { title: 'PR', width: 66, render: (_, row) => row.url ? <Link href={row.url} target="_blank">{row.number ? `#${row.number}` : row.sha?.slice(0, 7)}</Link> : row.number ? `#${row.number}` : row.sha?.slice(0, 7) },
                    { title: '合入时间', dataIndex: 'merged_at', width: 112, render: value => value ? <span title={formatTimezone(value)}>{formatTimezone(value, 'MM-DD HH:mm')}</span> : '未知' },
                    { title: '标题', dataIndex: 'title', width: 520, ellipsis: true },
                    { title: '作者', dataIndex: 'author', width: 100, ellipsis: true },
                    { title: 'Commit', width: 78, render: (_, row) => row.commit_url ? <Link href={row.commit_url} target="_blank">{row.sha?.slice(0, 7)}</Link> : row.sha?.slice(0, 7) },
                  ]} />
                </div>}
              {(comparison.data.pr_changes.revert_commits?.length || 0) > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginTop: 8 }}
                  message={`${revertRelations.length} 组 PR 回退关系：${cancelledRelationCount} 组区间内抵消，${retainedRelationCount} 组单方在区间不抵消`}
                  description={(
                    <Space direction="vertical" size={2}>
                      {(comparison.data.pr_changes.revert_commits || []).map(item => (
                        <span key={`${item.sha}-${item.reverted_pr}`}>
                          {item.revert_pr ? <Link href={`https://github.com/vllm-project/vllm-ascend/pull/${item.revert_pr}`} target="_blank">#{item.revert_pr}</Link> : '回退提交'}
                          {' 回退 '}
                          <Link href={`https://github.com/vllm-project/vllm-ascend/pull/${item.reverted_pr}`} target="_blank">#{item.reverted_pr}</Link>
                          {item.url && <>（<Link href={item.url} target="_blank">Commit</Link>）</>}
                          <Tag color={item.cancellation_status === 'cancelled' ? 'green' : 'gold'} style={{ marginLeft: 8 }}>
                            {item.cancellation_status === 'cancelled' ? '双方在区间，已抵消' : '单方在区间，不抵消'}
                          </Tag>
                        </span>
                      ))}
                      {(comparison.data.pr_changes.revert_commits || []).length === 0 && comparison.data.pr_changes.reverted_prs!.map(item => <span key={item.number}>#{item.number} {item.title}</span>)}
                    </Space>
                  )}
                />
              )}
            </> },
            { key: 'stage', label: '失败阶段差异', children: <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>{stageCard('Start', comparison.data.failure_stage_difference.start)}{stageCard('End', comparison.data.failure_stage_difference.end)}</div> },
            {
              key: 'logs',
              label: `区间日志汇总（${intervalRecords.length} 个节点）`,
              children: intervalLogSummaries.isLoading
                ? <div style={{ padding: 20, textAlign: 'center' }}><Spin tip="正在汇总区间日志" /></div>
                : <Space direction="vertical" size={8} style={{ width: '100%' }}>
                    {(intervalLogSummaries.data || []).map(({ record, summary, source }) => (
                      <div key={record.job_id} style={{ borderLeft: `3px solid ${record.conclusion === 'success' ? '#237b4b' : '#b72f3a'}`, padding: '6px 10px', background: '#fafafa' }}>
                        <Space size={8} wrap>
                          <Text strong>{formatTimezone(record.started_at)}</Text>
                          <Tag color={record.conclusion === 'success' ? 'success' : 'error'}>{record.conclusion === 'success' ? '成功' : '失败'}</Tag>
                          <Text type="secondary">{source}</Text>
                        </Space>
                        <div style={{ marginTop: 4 }}>{summary}</div>
                      </div>
                    ))}
                  </Space>,
            },
          ]} />
        </div>
      )}
      <Modal
        open={Boolean(summaryJobId)}
        onCancel={() => setSummaryJobId(null)}
        title="日志根因摘要"
        width={760}
        footer={<Button onClick={() => setSummaryJobId(null)}>关闭</Button>}
      >
        {storedSummary.isLoading ? <div style={{ padding: 30, textAlign: 'center' }}><Spin /></div> : storedSummary.data?.status === 'completed' ? (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Alert
              type="error"
              showIcon
              message="根因摘要"
              description={storedSummary.data.summary}
              action={(
                <Button
                  type="primary"
                  icon={<RobotOutlined />}
                  loading={createSummary.isPending}
                  onClick={() => createSummary.mutate()}
                >
                  重新生成
                </Button>
              )}
            />
            <Text type="secondary">
              {storedSummary.data.llm_provider}/{storedSummary.data.llm_model} · {storedSummary.data.generation_time_seconds ?? '-'}s · 已持久化
            </Text>
            <Collapse size="small" items={[{ key: 'log', label: '查看提交给模型的日志证据', children: <pre style={{ maxHeight: 360, overflow: 'auto', whiteSpace: 'pre-wrap', fontSize: 12 }}>{storedSummary.data.log_excerpt}</pre> }]} />
          </Space>
        ) : (
          <Alert
            type={storedSummary.data?.status === 'failed' ? 'error' : 'info'}
            showIcon
            message={storedSummary.data?.status === 'failed' ? '上次生成失败' : '尚未生成根因摘要'}
            description={storedSummary.data?.error_message || '点击后只下载日志并调用一次模型生成根因摘要，不执行故障修复、代码分析或多 Agent 流程。结果将按 Job 永久保存。'}
            action={<Button type="primary" icon={<RobotOutlined />} loading={createSummary.isPending} onClick={() => createSummary.mutate()}>{storedSummary.data?.status === 'failed' ? '重试' : '生成摘要'}</Button>}
          />
        )}
      </Modal>
    </Card>
  )
}
