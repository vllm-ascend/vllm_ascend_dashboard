import { useParams, useNavigate } from 'react-router-dom'
import { Card, Descriptions, Tag, Spin, Typography, Space, Button, Row, Col, Statistic, Timeline, Badge, Avatar } from 'antd'
import { ArrowLeftOutlined, GithubOutlined, CheckCircleOutlined, ClockCircleOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { usePRDetail } from '../hooks/usePRPipeline'
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

const reviewerStateColorMap: Record<string, string> = {
  APPROVED: 'success',
  CHANGES_REQUESTED: 'warning',
  PENDING: 'default',
  COMMENTED: 'processing',
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

  if (isNaN(parsedNumber)) {
    return (
      <div style={{ padding: 24 }}>
        <Card>
          <Space direction="vertical" align="center">
            <ExclamationCircleOutlined style={{ fontSize: 48, color: '#ff4d4f' }} />
            <Title level={4}>无效的 PR 编号</Title>
            <Text>请提供有效的 PR 编号</Text>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/pr-pipeline')}>
              返回 PR Pipeline
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
              返回 PR Pipeline
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
              返回 PR Pipeline
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
            {pr.state}
          </Tag>
        </Space>
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
              <Text type="secondary">{pr.changed_files} files</Text>
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="Pipeline 阶段">
            <Tag color={stageColorMap[pr.pipeline_stage || ''] || 'default'}>
              {pr.pipeline_stage || '-'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Review 状态">
            <Tag color={reviewStatusColorMap[pr.review_status || ''] || 'default'}>
              {pr.review_status || '-'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="CI 状态">
            <Tag color={ciStatusColorMap[pr.ci_status || ''] || 'default'}>
              {pr.ci_status || '-'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Draft">
            <Badge status={pr.is_draft ? 'warning' : 'success'} text={pr.is_draft ? 'Yes' : 'No'} />
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
        <Card title="Reviewers" style={{ marginBottom: 24 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            {pr.reviewers.map((reviewer) => (
              <Space key={reviewer.login} size="middle">
                <Avatar size="small" src={reviewer.avatar_url} style={{ backgroundColor: '#1677ff' }}>
                  {reviewer.login[0]?.toUpperCase()}
                </Avatar>
                <Text>{reviewer.login}</Text>
                <Tag color={reviewerStateColorMap[reviewer.state] || 'default'}>
                  {reviewer.state}
                </Tag>
              </Space>
            ))}
          </Space>
        </Card>
      )}
    </div>
  )
}

export default PRDetail
