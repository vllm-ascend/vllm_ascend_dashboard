import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Alert, Button, Card, DatePicker, Descriptions, Empty, Form, Input, message, Modal, Radio, Select, Space, Spin, Tag, Typography } from 'antd'
import { ArrowLeftOutlined, DownloadOutlined, GithubOutlined, ReloadOutlined, RobotOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'
import { useCurrentUser } from '../hooks/useCurrentUser'
import { useDailyData } from '../hooks/useDailySummary'
import {
  useAssignCommitAnalysis,
  useClaimCommitAnalysis,
  useCommitAnalysis,
  useRegenerateCommitAISummary,
  useUpdateCommitAnalysis,
} from '../hooks/useCommitAnalysis'
import {
  CHANGE_TYPES,
  CommitAnalysis,
  CommitAnalysisStatus,
  CommitChangeType,
} from '../services/commitAnalysis'
import { DailyCommitItem, GitHubActor } from '../services/dailySummary'
import '../components/GitHubActivityPanel.css'

dayjs.extend(utc)
dayjs.extend(timezone)

const { Text, Title } = Typography
const { TextArea } = Input
const BEIJING_TIMEZONE = 'Asia/Shanghai'
const NOT_APPLICABLE = '不涉及'

const getActorName = (actor: GitHubActor) => {
  if (!actor) return '-'
  return typeof actor === 'string' ? actor : actor.login
}

const getStatusColor = (status: CommitAnalysisStatus) => {
  if (status === '已闭环') return 'green'
  if (status === '已分析') return 'blue'
  return 'orange'
}

const getChangeTypeColor = (type: CommitChangeType) => {
  const colors: Record<CommitChangeType, string> = {
    Feature: 'green',
    Bugfix: 'red',
    Refactor: 'purple',
    Common: 'default',
    Test: 'cyan',
    CI: 'gold',
    Other: 'default',
  }
  return colors[type]
}

const normalizeText = (value: string | null | undefined) => {
  const normalized = value?.trim()
  return normalized || null
}

function CommitAnalysisDetail() {
  const { project, sha } = useParams<{ project: string; sha: string }>()
  const [searchParams] = useSearchParams()
  const date = searchParams.get('date') || dayjs().subtract(1, 'day').format('YYYY-MM-DD')
  const navigate = useNavigate()
  const [form] = Form.useForm()
  const [assignForm] = Form.useForm()
  const [isAssignModalOpen, setIsAssignModalOpen] = useState(false)

  const { data: currentUser } = useCurrentUser()
  const { data: dailyData } = useDailyData(project || '', date)
  const { data: analysis, isLoading } = useCommitAnalysis(project || '', sha || '')
  const claimMutation = useClaimCommitAnalysis()
  const assignMutation = useAssignCommitAnalysis()
  const updateMutation = useUpdateCommitAnalysis()
  const regenerateAISummaryMutation = useRegenerateCommitAISummary()

  const commit = useMemo<DailyCommitItem | undefined>(() => {
    return dailyData?.commits.find((item) => item.sha === sha)
  }, [dailyData, sha])

  const isAdmin = currentUser?.role === 'admin' || currentUser?.role === 'super_admin'
  const isSuperAdmin = currentUser?.role === 'super_admin'
  const projectTitle = project === 'vllm' ? 'vLLM' : 'vLLM Ascend'
  const impactApplicability = Form.useWatch('impact_applicability', form)
  const nextPlanApplicability = Form.useWatch('next_plan_applicability', form)

  useEffect(() => {
    if (!analysis) return
    form.setFieldsValue({
      what_commit_did: analysis.what_commit_did,
      change_type: analysis.change_type,
      affects_api: analysis.affects_api,
      impact_applicability: analysis.vllm_ascend_impact === NOT_APPLICABLE ? NOT_APPLICABLE : '涉及',
      vllm_ascend_impact: analysis.vllm_ascend_impact === NOT_APPLICABLE ? null : analysis.vllm_ascend_impact,
      next_plan_applicability: analysis.next_plan === NOT_APPLICABLE ? NOT_APPLICABLE : '涉及',
      next_plan: analysis.next_plan === NOT_APPLICABLE ? null : analysis.next_plan,
      planned_closure_time: analysis.planned_closure_time ? dayjs(analysis.planned_closure_time) : null,
      actual_closure_time: analysis.actual_closure_time ? dayjs(analysis.actual_closure_time) : null,
    })
    assignForm.setFieldsValue({ assignee: analysis.assignee })
  }, [analysis, assignForm, form])

  const handleImpactApplicabilityChange = (value: string) => {
    if (value === NOT_APPLICABLE) {
      form.setFieldValue('vllm_ascend_impact', null)
    }
  }

  const handleNextPlanApplicabilityChange = (value: string) => {
    if (value === NOT_APPLICABLE) {
      const today = dayjs().startOf('day')
      form.setFieldsValue({
        next_plan: null,
        planned_closure_time: today,
        actual_closure_time: today,
      })
    }
  }

  const handleClaim = async () => {
    if (!project || !sha) return
    try {
      await claimMutation.mutateAsync({ project, sha })
      message.success('认领成功')
    } catch (error: any) {
      message.error(error.response?.data?.detail || '认领失败')
    }
  }

  const handleAssign = async () => {
    if (!project || !sha) return
    const values = await assignForm.validateFields()
    try {
      await assignMutation.mutateAsync({ project, sha, assignee: values.assignee })
      message.success('分配成功')
      setIsAssignModalOpen(false)
    } catch (error: any) {
      message.error(error.response?.data?.detail || '分配失败')
    }
  }

  const handleSave = async () => {
    if (!project || !sha) return
    const values = await form.validateFields()
    try {
      await updateMutation.mutateAsync({
        project,
        sha,
        data: {
          what_commit_did: normalizeText(values.what_commit_did),
          change_type: values.change_type || null,
          affects_api: values.affects_api,
          vllm_ascend_impact: values.impact_applicability === NOT_APPLICABLE ? NOT_APPLICABLE : normalizeText(values.vllm_ascend_impact),
          next_plan: values.next_plan_applicability === NOT_APPLICABLE ? NOT_APPLICABLE : normalizeText(values.next_plan),
          planned_closure_time: values.planned_closure_time?.toISOString() || null,
          actual_closure_time: values.actual_closure_time?.toISOString() || null,
        },
      })
      message.success('保存成功')
    } catch (error: any) {
      message.error(error.response?.data?.detail || '保存失败')
    }
  }

  const handleRegenerateAISummary = async () => {
    if (!project || !sha) return
    try {
      await regenerateAISummaryMutation.mutateAsync({ project, sha, date })
      message.success('AI 总结生成成功')
    } catch (error: any) {
      message.error(error.response?.data?.detail || 'AI 总结生成失败')
    }
  }

  const handleExportAISummary = () => {
    if (!analysis?.ai_summary_markdown) {
      message.warning('暂无可导出的 AI 总结')
      return
    }

    const exportContent = `# ${projectTitle} Commit AI 总结

SHA：${sha}

提交信息：${commit?.message || '-'}

生成时间：${analysis.ai_summary_generated_at ? dayjs(analysis.ai_summary_generated_at).tz(BEIJING_TIMEZONE).format('YYYY-MM-DD HH:mm:ss') : '-'}

---

${analysis.ai_summary_markdown}
`
    const blob = new Blob([exportContent], { type: 'text/markdown;charset=utf-8' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = `${project}_commit_${sha?.slice(0, 7)}_ai_summary.md`
    link.click()
    URL.revokeObjectURL(link.href)
    message.success('AI 总结已导出')
  }

  const renderAnalysisHeader = (analysis: CommitAnalysis) => (
    <Space wrap>
      <Tag color={getStatusColor(analysis.status)}>{analysis.status}</Tag>
      {analysis.assignee ? <Tag>{analysis.assignee}</Tag> : <Tag color="default">未分配</Tag>}
      {analysis.change_type && <Tag color={getChangeTypeColor(analysis.change_type)}>{analysis.change_type}</Tag>}
    </Space>
  )

  const renderAISummary = () => {
    if (regenerateAISummaryMutation.isPending) {
      return (
        <div style={{ textAlign: 'center', padding: '48px 20px' }}>
          <Spin size="large" tip="正在调用 AI 生成 Commit 总结，预计需要 30-60 秒..." />
          <div style={{ marginTop: 16, color: '#8c8c8c' }}>AI 正在分析 Commit 数据，请勿关闭页面</div>
        </div>
      )
    }

    if (analysis?.ai_summary_status === 'failed') {
      return (
        <Alert
          message="AI 总结生成失败"
          description={analysis.ai_summary_error_message || '请稍后重试'}
          type="error"
          showIcon
          action={isSuperAdmin ? (
            <Button size="small" icon={<ReloadOutlined />} onClick={handleRegenerateAISummary}>
              重新生成
            </Button>
          ) : undefined}
        />
      )
    }

    if (!analysis?.ai_summary_markdown || analysis.ai_summary_status === 'not_generated') {
      return (
        <Empty description={isSuperAdmin ? '暂未生成 AI 总结，请点击生成按钮' : '暂未生成 AI 总结'} image={Empty.PRESENTED_IMAGE_SIMPLE}>
          {isSuperAdmin && (
            <Button type="primary" icon={<RobotOutlined />} onClick={handleRegenerateAISummary}>
              生成总结
            </Button>
          )}
        </Empty>
      )
    }

    return (
      <div className="ai-summary-container">
        <div className="summary-meta" style={{ marginBottom: 16 }}>
          <Space wrap>
            {analysis.ai_summary_generated_at && (
              <Tag>生成时间：{dayjs(analysis.ai_summary_generated_at).tz(BEIJING_TIMEZONE).format('YYYY-MM-DD HH:mm')}</Tag>
            )}
            {analysis.ai_summary_generated_by && <Tag>生成者：{analysis.ai_summary_generated_by}</Tag>}
            {analysis.ai_summary_llm_provider && <Tag color="blue">{analysis.ai_summary_llm_provider}</Tag>}
            {analysis.ai_summary_llm_model && <Tag>{analysis.ai_summary_llm_model}</Tag>}
          </Space>
          <Space style={{ marginLeft: 16 }}>
            <Button size="small" icon={<DownloadOutlined />} onClick={handleExportAISummary}>
              导出
            </Button>
            {isSuperAdmin && (
              <Button size="small" icon={<ReloadOutlined />} onClick={handleRegenerateAISummary}>
                重新生成
              </Button>
            )}
          </Space>
        </div>
        <div style={{ padding: 20, background: '#fafafa', borderRadius: 8, maxHeight: 600, overflowY: 'auto' }}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {analysis.ai_summary_markdown}
          </ReactMarkdown>
        </div>
      </div>
    )
  }

  return (
    <div className="stripe-page-container">
      <div className="stripe-page-header">
        <Button
          type="default"
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate(`/github-activity/${project}`)}
          className="stripe-btn-ghost stripe-btn-sm"
        >
          返回
        </Button>
        <Title level={3} className="stripe-page-title" style={{ margin: 0 }}>
          {projectTitle} - Commit 分析
        </Title>
        <Space style={{ marginLeft: 'auto' }}>
          {analysis && !analysis.assignee && (
            <Button onClick={handleClaim} loading={claimMutation.isPending}>认领</Button>
          )}
          {isAdmin && (
            <Button onClick={() => setIsAssignModalOpen(true)}>分配责任人</Button>
          )}
        </Space>
      </div>

      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card className="stripe-card" loading={isLoading}>
          {analysis && (
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              {renderAnalysisHeader(analysis)}
              <Descriptions bordered column={2}>
                <Descriptions.Item label="SHA" span={2}>
                  <Space>
                    <Text code copyable>{sha}</Text>
                    {commit?.html_url && (
                      <a href={commit.html_url} target="_blank" rel="noopener noreferrer">
                        <GithubOutlined /> GitHub
                      </a>
                    )}
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="提交信息" span={2}>{commit?.message || '-'}</Descriptions.Item>
                <Descriptions.Item label="作者">{getActorName(commit?.author || null)}</Descriptions.Item>
                <Descriptions.Item label="提交时间">
                  {commit?.committed_at ? dayjs(commit.committed_at).tz(BEIJING_TIMEZONE).format('YYYY-MM-DD HH:mm') : '-'}
                </Descriptions.Item>
                {commit?.pr_number && (
                  <Descriptions.Item label="关联 PR" span={2}>
                    #{commit.pr_number}: {commit.pr_title}
                  </Descriptions.Item>
                )}
              </Descriptions>
            </Space>
          )}
        </Card>

        <Card className="stripe-card" title="AI 总结" loading={isLoading}>
          {renderAISummary()}
        </Card>

        <Card className="stripe-card" title="分析内容">
          <Form form={form} layout="vertical" disabled={!analysis?.can_edit}>
            <Form.Item label="修改类型" name="change_type">
              <Select allowClear placeholder="选择修改类型">
                {CHANGE_TYPES.map((type) => (
                  <Select.Option key={type} value={type}>{type}</Select.Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item label="Commit分析" name="what_commit_did">
              <TextArea rows={4} placeholder="描述 commit 的主要修改内容" />
            </Form.Item>
            <Form.Item label="是否影响 API" name="affects_api">
              <Radio.Group>
                <Radio value={true}>是</Radio>
                <Radio value={false}>否</Radio>
              </Radio.Group>
            </Form.Item>
            <Form.Item label="对 vllm-ascend 的影响" name="impact_applicability">
              <Radio.Group onChange={(event) => handleImpactApplicabilityChange(event.target.value)}>
                <Radio value="涉及">涉及</Radio>
                <Radio value={NOT_APPLICABLE}>不涉及</Radio>
              </Radio.Group>
            </Form.Item>
            <Form.Item name="vllm_ascend_impact">
              <TextArea
                rows={4}
                placeholder="说明对项目功能、稳定性、性能、兼容性等方面的影响"
                disabled={impactApplicability === NOT_APPLICABLE}
              />
            </Form.Item>
            <Form.Item label="下一步计划" name="next_plan_applicability">
              <Radio.Group onChange={(event) => handleNextPlanApplicabilityChange(event.target.value)}>
                <Radio value="涉及">涉及</Radio>
                <Radio value={NOT_APPLICABLE}>不涉及</Radio>
              </Radio.Group>
            </Form.Item>
            <Form.Item name="next_plan">
              <TextArea
                rows={3}
                placeholder="说明后续跟进计划"
                disabled={nextPlanApplicability === NOT_APPLICABLE}
              />
            </Form.Item>
            <Space size={16} style={{ width: '100%' }}>
              <Form.Item label="计划闭环时间" name="planned_closure_time">
                <DatePicker showTime format="YYYY-MM-DD HH:mm" />
              </Form.Item>
              <Form.Item label="实际闭环时间" name="actual_closure_time">
                <DatePicker showTime format="YYYY-MM-DD HH:mm" />
              </Form.Item>
            </Space>
            <Form.Item style={{ marginBottom: 0 }}>
              <Button
                type="primary"
                onClick={handleSave}
                loading={updateMutation.isPending}
                disabled={!analysis?.can_edit}
              >
                保存分析
              </Button>
            </Form.Item>
          </Form>
        </Card>
      </Space>

      <Modal
        title="分配责任人"
        open={isAssignModalOpen}
        onCancel={() => setIsAssignModalOpen(false)}
        onOk={handleAssign}
        confirmLoading={assignMutation.isPending}
        forceRender
      >
        <Form form={assignForm} layout="vertical">
          <Form.Item name="assignee" label="责任人" rules={[{ required: true, message: '请输入责任人' }]}>
            <Input placeholder="输入责任人用户名或名称" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default CommitAnalysisDetail
