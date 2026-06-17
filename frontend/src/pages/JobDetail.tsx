import { useParams, useNavigate } from 'react-router-dom'
import { Card, Button, Space, Typography, Tag, Descriptions, Timeline, Empty, Alert, message, Spin } from 'antd'
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  SyncOutlined,
  GithubOutlined,
  RobotOutlined,
  BulbOutlined,
} from '@ant-design/icons'
import { useJobDetail, useJobAnalysis, useTriggerJobAnalysis } from '../hooks/useCI'
import { useJobOwners } from '../hooks/useJobOwners'
import { formatTimezone } from '../utils/timezone'
import { renderStatusTag, renderConclusionTag, formatDuration, renderHardwareTag } from '../utils/ciRenderers'

const { Title, Text } = Typography

// Step 状态标签
const renderStepStatus = (status: string, conclusion: string | null) => {
  if (status === 'completed') {
    if (conclusion === 'success') {
      return <Tag color="success" icon={<CheckCircleOutlined />}>成功</Tag>
    } else if (conclusion === 'failure') {
      return <Tag color="error" icon={<CloseCircleOutlined />}>失败</Tag>
    } else if (conclusion === 'skipped') {
      return <Tag color="default">跳过</Tag>
    }
    return <Tag color="warning">{conclusion || '-'}</Tag>
  } else if (status === 'in_progress') {
    return <Tag color="processing" icon={<SyncOutlined spin />}>进行中</Tag>
  } else if (status === 'queued') {
    return <Tag color="default" icon={<ClockCircleOutlined />}>等待中</Tag>
  }
  return <Tag color="default">{status}</Tag>
}

function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const jobIdNum = jobId ? parseInt(jobId) : null

  const { data: job, isLoading, refetch } = useJobDetail(jobIdNum)
  const { data: jobOwners } = useJobOwners()
  const { data: analysis, isLoading: analysisLoading } = useJobAnalysis(jobIdNum)
  const triggerAnalysis = useTriggerJobAnalysis()

  // 查找 display_name
  const ownerInfo = jobOwners?.find(
    (o) => o.workflow_name === job?.workflow_name && o.job_name === job?.job_name
  )
  const displayName = ownerInfo?.display_name

  // 刷新数据
  const handleRefresh = async () => {
    try {
      await refetch()
      message.success('数据已刷新')
    } catch (error) {
      message.error('刷新失败')
    }
  }

  // 触发 AI 分析
  const handleAnalyze = async () => {
    if (!jobIdNum) return
    try {
      await triggerAnalysis.mutateAsync(jobIdNum)
      message.success('AI 分析完成')
    } catch (error: any) {
      const msg = error?.response?.data?.detail || '分析失败'
      message.error(msg)
    }
  }

  if (isLoading) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <Empty description="加载中..." />
      </div>
    )
  }

  if (!job) {
    return (
      <div style={{ padding: 24 }}>
        <Alert
          message="Job 不存在"
          description="找不到该 Job 的信息"
          type="error"
          showIcon
        />
        <Button style={{ marginTop: 16 }} onClick={() => navigate('/ci')}>
          返回 CI 看板
        </Button>
      </div>
    )
  }

  return (
    <div style={{ padding: 24 }}>
      {/* 返回按钮和标题 */}
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/ci/runs/${job.run_id}`)}>
          返回 Workflow 详情
        </Button>
        {job.github_job_url && (
          <Button
            icon={<GithubOutlined />}
            href={job.github_job_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            在 GitHub 上查看
          </Button>
        )}
      </Space>

      <Title level={2} style={{ marginBottom: 24 }}>
        Job 详情
      </Title>

      {/* Job 基本信息 */}
      <Card style={{ marginBottom: 24 }}>
        <Descriptions column={4} bordered>
          <Descriptions.Item label="Job 名称" span={2}>
            <Space direction="vertical" size={0}>
              <Text strong>{job.job_name}</Text>
              {displayName && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {displayName}
                </Text>
              )}
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="Job ID">#{job.job_id}</Descriptions.Item>
          
          <Descriptions.Item label="Workflow">{job.workflow_name}</Descriptions.Item>
          <Descriptions.Item label="Run ID">#{job.run_id}</Descriptions.Item>
          <Descriptions.Item label="硬件">
            {renderHardwareTag(job.hardware)}
          </Descriptions.Item>
          <Descriptions.Item label="Runner">
            {job.runner_name || (job.runner_labels && job.runner_labels.length > 0 ? job.runner_labels.join(', ') : '-')}
          </Descriptions.Item>

          <Descriptions.Item label="状态">
            {renderStatusTag(job.status)}
          </Descriptions.Item>
          <Descriptions.Item label="结果">
            {renderConclusionTag(job.conclusion)}
          </Descriptions.Item>
          <Descriptions.Item label="时长">
            {formatDuration(job.duration_seconds)}
          </Descriptions.Item>

          <Descriptions.Item label="开始时间">
            {job.started_at ? formatTimezone(job.started_at) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="完成时间">
            {job.completed_at ? formatTimezone(job.completed_at) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {formatTimezone(job.created_at)}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* Runner 标签 */}
      {job.runner_labels && job.runner_labels.length > 0 && (
        <Card title="Runner 标签" style={{ marginBottom: 24 }}>
          <Space wrap>
            {job.runner_labels.map((label: string, index: number) => (
              <Tag key={index} color="blue">{label}</Tag>
            ))}
          </Space>
        </Card>
      )}

      {/* Steps 详情 */}
      <Card title="Steps 详情" style={{ marginBottom: 24 }}>
        {job.steps_data && job.steps_data.length > 0 ? (
          <Timeline
            items={job.steps_data.map((step: any, index: number) => {
              const isFailure = step.conclusion === 'failure'
              
              return {
                key: index,
                color: isFailure ? 'red' : step.conclusion === 'success' ? 'green' : 'gray',
                children: (
                  <div style={{ padding: '12px 0' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                      <Space>
                        <Text strong>Step {step.number}: {step.name}</Text>
                        {isFailure && (
                          <Tag color="error" icon={<CloseCircleOutlined />}>失败</Tag>
                        )}
                      </Space>
                      {renderStepStatus(step.status, step.conclusion)}
                    </div>
                    
                    {isFailure && (
                      <Alert
                        message={
                          <Space>
                            <span>此步骤失败，请查看 GitHub 日志获取详细信息</span>
                            <Button
                              type="link"
                              size="small"
                              icon={<GithubOutlined />}
                              href={job.github_job_url}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              在 GitHub 上查看日志
                            </Button>
                          </Space>
                        }
                        type="error"
                        showIcon
                        style={{ marginTop: 8 }}
                        icon={<CloseCircleOutlined style={{ color: '#ff4d4f' }} />}
                      />
                    )}
                  </div>
                ),
              }
            })}
          />
        ) : (
          <Empty description="暂无 Steps 信息" />
        )}
      </Card>

      {/* AI 分析结果 — 仅失败 job 显示 */}
      {(job.conclusion === 'failure' || job.conclusion === 'cancelled') && (
        <Card
          title={
            <Space>
              <RobotOutlined />
              <span>AI 失败分析</span>
              <Tag color="purple">Claude Code CLI</Tag>
            </Space>
          }
          style={{ marginBottom: 24 }}
        >
          {analysisLoading ? (
            <div style={{ textAlign: 'center', padding: 24 }}>
              <Spin tip="正在加载分析结果..." />
            </div>
          ) : analysis ? (
            <div>
              <Descriptions column={3} size="small" bordered style={{ marginBottom: 16 }}>
                <Descriptions.Item label="根因分类">
                  <Tag color={
                    analysis.root_cause_category === 'code_bug' ? 'red' :
                    analysis.root_cause_category === 'env_issue' ? 'orange' :
                    analysis.root_cause_category === 'infra' ? 'purple' :
                    analysis.root_cause_category === 'flaky_test' ? 'gold' :
                    analysis.root_cause_category === 'timeout' ? 'volcano' :
                    'default'
                  }>
                    {analysis.root_cause_category || 'unknown'}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="置信度">
                  {analysis.confidence === 'high' ? '🟢 高' :
                   analysis.confidence === 'medium' ? '🟡 中' : '🔴 低'}
                </Descriptions.Item>
                <Descriptions.Item label="分析时间">
                  {analysis.analyzed_at ? formatTimezone(analysis.analyzed_at) : '-'}
                </Descriptions.Item>
              </Descriptions>

              <Card type="inner" title="根因分析" style={{ marginBottom: 12 }}>
                <div style={{ whiteSpace: 'pre-wrap' }}>
                  {analysis.analysis_markdown || '暂无详细分析'}
                </div>
              </Card>

              {analysis.suggested_fix && (
                <Card
                  type="inner"
                  title={<Space><BulbOutlined />修复建议</Space>}
                  style={{ marginBottom: 12, borderLeft: '3px solid #52c41a' }}
                >
                  <div style={{ whiteSpace: 'pre-wrap' }}>
                    {analysis.suggested_fix}
                  </div>
                </Card>
              )}

              {analysis.related_commits && analysis.related_commits.length > 0 && (
                <Card type="inner" title="相关 Commits" size="small">
                  <Space wrap>
                    {analysis.related_commits.map((sha: string) => (
                      <Tag key={sha} color="blue">
                        <code>{sha.slice(0, 7)}</code>
                      </Tag>
                    ))}
                  </Space>
                </Card>
              )}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: 24 }}>
              <Empty description="暂无 AI 分析结果">
                <Button
                  type="primary"
                  icon={<RobotOutlined />}
                  onClick={handleAnalyze}
                  loading={triggerAnalysis.isPending}
                >
                  AI 分析失败原因
                </Button>
              </Empty>
            </div>
          )}
        </Card>
      )}
    </div>
  )
}

export default JobDetail
