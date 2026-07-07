import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Descriptions, Tag, Spin, Typography, Space, Button, Row, Col, Statistic, Timeline, Badge, Avatar, Alert } from 'antd'
import { ArrowLeftOutlined, GithubOutlined, CheckCircleOutlined, ClockCircleOutlined, ExclamationCircleOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { usePRDetail, usePRDiagnosis } from '../hooks/usePRPipeline'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import dayjs from 'dayjs'

const { Title, Text } = Typography

const stageColorMap: Record<string, string> = {
  submitted: 'default',
  reviewing: 'processing',
  approved: 'success',
  ci_running: 'warning',
  ci_passed: 'lime',
  ci_failed: 'error',
  merging: 'purple',
  merged: 'cyan',
  closed: 'default',
}

const stateColorMap: Record<string, string> = {
  open: 'blue',
  merged: 'green',
  closed: 'red',
}

const reviewStatusColorMap: Record<string, string> = {
  none: 'default',
  reviewing: 'processing',
  approved: 'success',
  changes_requested: 'warning',
}

const ciStatusColorMap: Record<string, string> = {
  success: 'success',
  failure: 'error',
  in_progress: 'processing',
  queued: 'default',
  cancelled: 'warning',
}

const stageLabelMap: Record<string, string> = {
  submitted: '已提交',
  reviewing: '评审中',
  approved: '已通过',
  ci_running: 'CI 运行中',
  ci_passed: 'CI 通过',
  ci_failed: 'CI 失败',
  merging: '合并中',
  merged: '已合并',
  closed: '已关闭',
}

const stateLabelMap: Record<string, string> = {
  open: '开启',
  merged: '已合并',
  closed: '已关闭',
}

const reviewStatusLabelMap: Record<string, string> = {
  none: '无',
  reviewing: '评审中',
  approved: '已通过',
  changes_requested: '要求修改',
}

const ciStatusLabelMap: Record<string, string> = {
  success: '通过',
  failure: '失败',
  in_progress: '运行中',
  queued: '排队中',
  cancelled: '已取消',
}

const reviewerStateColorMap: Record<string, string> = {
  APPROVED: 'success',
  CHANGES_REQUESTED: 'warning',
  PENDING: 'default',
  COMMENTED: 'processing',
}

const reviewerStateLabelMap: Record<string, string> = {
  APPROVED: '已通过',
  CHANGES_REQUESTED: '要求修改',
  PENDING: '等待中',
  COMMENTED: '已评论',
}

const stageIconMap: Record<string, typeof CheckCircleOutlined> = {
  submitted: ClockCircleOutlined,
  reviewing: ClockCircleOutlined,
  approved: CheckCircleOutlined,
  ci_running: ClockCircleOutlined,
  ci_passed: CheckCircleOutlined,
  ci_failed: ExclamationCircleOutlined,
  merging: ClockCircleOutlined,
  merged: CheckCircleOutlined,
  closed: ExclamationCircleOutlined,
}

const PRDetail = () => {
  const { prNumber } = useParams<{ prNumber: string }>()
  const navigate = useNavigate()
  const parsedNumber = prNumber ? Number(prNumber) : NaN
  const { data: pr, isLoading, error } = usePRDetail(parsedNumber)

  const [diagnosisResult, setDiagnosisResult] = useState<string | null>(null)
  const diagnosisMutation = usePRDiagnosis()

  useEffect(() => {
    setDiagnosisResult(null)
  }, [parsedNumber])

  if (isNaN(parsedNumber)) {
    return (
      <div style={{ padding: 24 }}>
        <Card>
          <Space direction="vertical" align="center">
            <ExclamationCircleOutlined style={{ fontSize: 48, color: '#ff4d4f' }} />
            <Title level={4}>无效的 PR 编号</Title>
            <Text>请提供有效的 PR 编号</Text>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/pr-pipeline')}>
              返回 PR 流水线
            </Button>
          </Space>
        </Card>
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <Card>
          <Space direction="vertical" align="center">
            <ExclamationCircleOutlined style={{ fontSize: 48, color: '#ff4d4f' }} />
            <Title level={4}>加载失败</Title>
            <Text>{(error as any)?.message || '无法获取 PR 详情'}</Text>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/pr-pipeline')}>
              返回 PR 流水线
            </Button>
          </Space>
        </Card>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!pr) {
    return (
      <div style={{ padding: 24 }}>
        <Card>
          <Space direction="vertical" align="center">
            <ExclamationCircleOutlined style={{ fontSize: 48, color: '#ff4d4f' }} />
            <Title level={4}>PR 不存在</Title>
            <Text>找不到该 PR 的信息</Text>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/pr-pipeline')}>
              返回 PR 流水线
            </Button>
          </Space>
        </Card>
      </div>
    )
  }

  const timelineItems = [
    {
      color: 'blue',
      children: (
        <div>
          <Text strong>创建</Text>
          <br />
          <Text type="secondary">{dayjs(pr.created_at).format('YYYY-MM-DD HH:mm')}</Text>
        </div>
      ),
    },
    ...(pr.first_review_at
      ? [
          {
            color: 'processing',
            children: (
              <div>
                <Text strong>首次 Review</Text>
                <br />
                <Text type="secondary">{dayjs(pr.first_review_at).format('YYYY-MM-DD HH:mm')}</Text>
                {pr.time_to_first_review_hours != null && (
                  <Tag color="blue" style={{ marginLeft: 8 }}>
                    {pr.time_to_first_review_hours.toFixed(1)}h
                  </Tag>
                )}
              </div>
            ),
          },
        ]
      : []),
    ...(pr.first_approved_at
      ? [
          {
            color: 'green',
            children: (
              <div>
                <Text strong>首次 Approved</Text>
                <br />
                <Text type="secondary">{dayjs(pr.first_approved_at).format('YYYY-MM-DD HH:mm')}</Text>
              </div>
            ),
          },
        ]
      : []),
    ...(pr.ci_started_at
      ? [
          {
            color: 'orange',
            children: (
              <div>
                <Text strong>CI 开始</Text>
                <br />
                <Text type="secondary">{dayjs(pr.ci_started_at).format('YYYY-MM-DD HH:mm')}</Text>
              </div>
            ),
          },
        ]
      : []),
    ...(pr.ci_completed_at
      ? [
          {
            color: pr.ci_status === 'success' ? 'green' : 'red',
            children: (
              <div>
                <Text strong>CI 完成</Text>
                <br />
                <Text type="secondary">{dayjs(pr.ci_completed_at).format('YYYY-MM-DD HH:mm')}</Text>
                {pr.ci_duration_hours != null && (
                  <Tag color={pr.ci_status === 'success' ? 'success' : 'error'} style={{ marginLeft: 8 }}>
                    {pr.ci_duration_hours.toFixed(1)}h
                  </Tag>
                )}
              </div>
            ),
          },
        ]
      : []),
    ...(pr.merged_at
      ? [
          {
            color: 'cyan',
            children: (
              <div>
                <Text strong>合并</Text>
                <br />
                <Text type="secondary">{dayjs(pr.merged_at).format('YYYY-MM-DD HH:mm')}</Text>
                {pr.time_to_merge_hours != null && (
                  <Tag color="cyan" style={{ marginLeft: 8 }}>
                    {pr.time_to_merge_hours.toFixed(1)}h
                  </Tag>
                )}
              </div>
            ),
          },
        ]
      : []),
    ...(pr.closed_at && !pr.merged_at
      ? [
          {
            color: 'red',
            children: (
              <div>
                <Text strong>关闭</Text>
                <br />
                <Text type="secondary">{dayjs(pr.closed_at).format('YYYY-MM-DD HH:mm')}</Text>
              </div>
            ),
          },
        ]
      : []),
  ]

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16 }} size="middle">
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/pr-pipeline')}>
          返回
        </Button>
        {pr.html_url && (
          <Button
            icon={<GithubOutlined />}
            href={pr.html_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            在 GitHub 上查看
          </Button>
        )}
      </Space>

      <div style={{ marginBottom: 24 }}>
        <Space align="center" size="middle">
          <Title level={3} style={{ margin: 0 }}>
            {pr.title}
          </Title>
          <Tag color="#108ee9">#{pr.pr_number}</Tag>
          <Tag color={stateColorMap[pr.state] || 'default'}>
            {stateLabelMap[pr.state] || pr.state}
          </Tag>
        </Space>
      </div>

      <div style={{ marginBottom: 24 }}>
        <Button
          type="primary"
          icon={<ThunderboltOutlined />}
          loading={diagnosisMutation.isPending}
          onClick={() => {
            setDiagnosisResult(null)
            diagnosisMutation.mutate(parsedNumber, {
              onSuccess: (data) => setDiagnosisResult(data.report),
              onError: () => setDiagnosisResult(null),
            })
          }}
        >
          AI 诊断
        </Button>
      </div>

      <Card style={{ marginBottom: 24 }}>
        <Descriptions column={2} bordered>
          <Descriptions.Item label="作者">
            <Space>
              {pr.author_avatar_url && (
                <Avatar src={pr.author_avatar_url} size="small" />
              )}
              <Text>{pr.author}</Text>
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="分支">
            <Space>
              <Tag color="blue">{pr.head_branch || '-'}</Tag>
              <Text>→</Text>
              <Tag color="green">{pr.base_branch || '-'}</Tag>
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="标签">
            {pr.labels && pr.labels.length > 0
              ? pr.labels.map((label) => <Tag key={label}>{label}</Tag>)
              : <Text type="secondary">无</Text>
            }
          </Descriptions.Item>
          <Descriptions.Item label="代码变更">
            <Space>
              <Text style={{ color: '#52c41a' }}>+{pr.additions}</Text>
              <Text style={{ color: '#ff4d4f' }}>-{pr.deletions}</Text>
              <Text type="secondary">{pr.changed_files} 个文件</Text>
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="流水线阶段">
            <Tag color={stageColorMap[pr.pipeline_stage || ''] || 'default'}>
              {stageLabelMap[pr.pipeline_stage || ''] || pr.pipeline_stage || '-'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Review 状态">
            <Tag color={reviewStatusColorMap[pr.review_status || ''] || 'default'}>
              {reviewStatusLabelMap[pr.review_status || ''] || pr.review_status || '-'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="CI 状态">
            <Tag color={ciStatusColorMap[pr.ci_status || ''] || 'default'}>
              {ciStatusLabelMap[pr.ci_status || ''] || pr.ci_status || '-'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="草稿">
            <Badge status={pr.is_draft ? 'warning' : 'success'} text={pr.is_draft ? '是' : '否'} />
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="PR 生命周期" style={{ marginBottom: 24 }}>
        <Timeline items={timelineItems} />
      </Card>

      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="首次 Review 耗时"
              value={pr.time_to_first_review_hours ?? '-'}
              suffix={pr.time_to_first_review_hours != null ? 'h' : ''}
              precision={1}
              valueStyle={pr.time_to_first_review_hours != null ? { color: '#1890ff' } : undefined}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="审批耗时"
              value={pr.time_to_approval_hours ?? '-'}
              suffix={pr.time_to_approval_hours != null ? 'h' : ''}
              precision={1}
              valueStyle={pr.time_to_approval_hours != null ? { color: '#52c41a' } : undefined}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="CI 耗时"
              value={pr.ci_duration_hours ?? '-'}
              suffix={pr.ci_duration_hours != null ? 'h' : ''}
              precision={1}
              valueStyle={pr.ci_duration_hours != null ? { color: '#faad14' } : undefined}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="合并耗时"
              value={pr.time_to_merge_hours ?? '-'}
              suffix={pr.time_to_merge_hours != null ? 'h' : ''}
              precision={1}
              valueStyle={pr.time_to_merge_hours != null ? { color: '#13c2c2' } : undefined}
            />
          </Card>
        </Col>
      </Row>

      {pr.reviewers && pr.reviewers.length > 0 && (
        <Card title="评审人" style={{ marginBottom: 24 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            {pr.reviewers.map((reviewer) => (
              <Space key={reviewer.login} size="middle">
                <Avatar size="small" src={reviewer.avatar_url} style={{ backgroundColor: '#1677ff' }}>
                  {reviewer.login[0]?.toUpperCase()}
                </Avatar>
                <Text>{reviewer.login}</Text>
                <Tag color={reviewerStateColorMap[reviewer.state] || 'default'}>
                  {reviewerStateLabelMap[reviewer.state] || reviewer.state}
                </Tag>
              </Space>
            ))}
          </Space>
        </Card>
      )}

      {diagnosisMutation.isError && (
        <Alert
          message="诊断失败"
          description={String(diagnosisMutation.error?.message || '未知错误')}
          type="error"
          closable
          style={{ marginTop: 16 }}
        />
      )}

      {diagnosisResult && (
        <Card
          title="🤖 AI 诊断报告"
          style={{ marginTop: 16 }}
          extra={
            diagnosisMutation.data && (
              <span style={{ fontSize: 12, color: '#94a3b8' }}>
                {diagnosisMutation.data.model} · {diagnosisMutation.data.duration_seconds}s · {diagnosisMutation.data.tokens} tokens
              </span>
            )
          }
        >
          <div style={{
            maxHeight: 600,
            overflowY: 'auto',
            padding: 16,
            background: '#f8fafc',
            borderRadius: 8,
            border: '1px solid #e2e8f0'
          }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {diagnosisResult}
            </ReactMarkdown>
          </div>
        </Card>
      )}
    </div>
  )
}

export default PRDetail
