import { useState } from 'react'
import {
  Card, Form, Input, InputNumber, Switch, Button, Space, Tag, Table,
  Alert, Descriptions, Modal, Typography, Divider, Spin, Empty, Row, Col,
  Tooltip, Badge,
} from 'antd'
import {
  MailOutlined, SendOutlined, SettingOutlined, HistoryOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined,
  ClockCircleOutlined, KeyOutlined, InfoCircleOutlined, ReloadOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import {
  useReportConfig, useUpdateReportConfig, useTriggerReport,
  useReportHistory, useLatestReport,
} from '../hooks/useDailyReport'
import type { DailyReportConfigUpdate, DailyReportHistoryItem } from '../services/dailyReport'
import { useCurrentUser } from '../hooks/useCurrentUser'
import './DailyReportConfig.tsx.css'

const { Text, Title } = Typography

function DailyReportConfigPage() {
  const { data: currentUser } = useCurrentUser()
  const isSuperAdmin = currentUser?.role === 'super_admin'

  const { data: config, isLoading: configLoading } = useReportConfig()
  const updateConfig = useUpdateReportConfig()
  const triggerReport = useTriggerReport()
  const { data: historyData, isLoading: historyLoading } = useReportHistory(20, 0)
  const { data: latestData, isLoading: latestLoading } = useLatestReport()

  const [configForm] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [triggering, setTriggering] = useState(false)
  const [triggerResult, setTriggerResult] = useState<{ success: boolean; message: string } | null>(null)
  const [triggerDate, setTriggerDate] = useState<string>('')

  const handleSaveConfig = async () => {
    try {
      const values = await configForm.validateFields()
      setSaving(true)
      const update: DailyReportConfigUpdate = {}
      if (values.report_recipients !== config?.report_recipients) update.report_recipients = values.report_recipients
      if (values.report_cc_recipients !== config?.report_cc_recipients) update.report_cc_recipients = values.report_cc_recipients
      if (values.report_subject_template !== config?.report_subject_template) update.report_subject_template = values.report_subject_template

      if (Object.keys(update).length === 0) {
        Modal.info({ title: '无变更', content: '配置没有变化，无需保存' })
        setSaving(false)
        return
      }

      await updateConfig.mutateAsync(update)
      Modal.success({ title: '保存成功', content: '报告配置已更新' })
    } catch {
    } finally {
      setSaving(false)
    }
  }

  const handleTrigger = async () => {
    setTriggering(true)
    setTriggerResult(null)
    try {
      const result = await triggerReport.mutateAsync(triggerDate || undefined)
      setTriggerResult({ success: result.success, message: result.message })
      if (result.success) {
        Modal.success({ title: '发送成功', content: `报告已发送，日期: ${result.report_date}` })
      } else {
        Modal.error({ title: '发送失败', content: result.message })
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : '未知错误'
      setTriggerResult({ success: false, message: errMsg })
    } finally {
      setTriggering(false)
    }
  }

  const renderSummaryCard = (label: string, value: string | number, className = '') => (
    <div className={`report-summary-card ${className}`}>
      <div className="value">{value}</div>
      <div className="label">{label}</div>
    </div>
  )

  const renderLatestReport = () => {
    if (latestLoading) return <Spin />
    if (!latestData || ('message' in latestData && latestData.message)) return <Empty description="暂无报告记录" />
    const report = latestData as Exclude<typeof latestData, { message: string; data: null }>
    const ci = report.ci_summary as Record<string, unknown> || {}
    const model = report.model_summary as Record<string, unknown> || {}
    const gh = report.github_summary as Record<string, unknown> || {}

    return (
      <Card className="stripe-card" title={<Space><HistoryOutlined />最新报告详情</Space>} size="small">
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="报告日期">{report.report_date}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={report.status === 'sent' ? 'green' : report.status === 'failed' ? 'red' : 'orange'}>
              {report.status === 'sent' ? '已发送' : report.status === 'failed' ? '发送失败' : '待发送'}
            </Tag>
          </Descriptions.Item>
        </Descriptions>
        <Divider orientation="left" plain>CI 概况</Divider>
        <div className="report-summary-grid">
          {renderSummaryCard('总运行数', ci.total_runs as number || 0)}
          {renderSummaryCard('通过', ci.success_runs as number || 0, 'success')}
          {renderSummaryCard('失败', ci.failure_runs as number || 0, 'danger')}
          {renderSummaryCard('通过率', `${(ci.success_rate as number || 0).toFixed(1)}%`,
            (ci.success_rate as number || 0) >= 90 ? 'success' : (ci.success_rate as number || 0) >= 70 ? 'warning' : 'danger')}
        </div>
        <Divider orientation="left" plain>模型验证</Divider>
        <div className="report-summary-grid">
          {renderSummaryCard('报告数', model.total_reports as number || 0)}
          {renderSummaryCard('Pass', model.pass_count as number || 0, 'success')}
          {renderSummaryCard('Fail', model.fail_count as number || 0, 'danger')}
          {renderSummaryCard('通过率', `${(model.pass_rate as number || 0).toFixed(1)}%`,
            (model.pass_rate as number || 0) >= 90 ? 'success' : 'warning')}
        </div>
        <Divider orientation="left" plain>GitHub 活动</Divider>
        <div className="report-summary-grid">
          {renderSummaryCard('PR', gh.pr_count as number || 0)}
          {renderSummaryCard('Issue', gh.issue_count as number || 0)}
          {renderSummaryCard('Commit', gh.commit_count as number || 0)}
          {renderSummaryCard('AI 概要', gh.ai_summary_snippet ? '有' : '无', gh.ai_summary_snippet ? 'success' : '')}
        </div>
      </Card>
    )
  }

  const historyColumns: ColumnsType<DailyReportHistoryItem> = [
    {
      title: '报告日期',
      dataIndex: 'report_date',
      key: 'report_date',
      width: 120,
      sorter: (a, b) => a.report_date.localeCompare(b.report_date),
      defaultSortOrder: 'descend',
    },
    {
      title: '主题',
      dataIndex: 'subject',
      key: 'subject',
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => (
        <Space size={4}>
          <span className={`report-status-dot ${status}`} />
          <Tag color={status === 'sent' ? 'green' : status === 'failed' ? 'red' : 'orange'}>
            {status === 'sent' ? '已发送' : status === 'failed' ? '失败' : '待发送'}
          </Tag>
        </Space>
      ),
    },
    {
      title: '收件人',
      dataIndex: 'recipients',
      key: 'recipients',
      ellipsis: true,
      width: 200,
    },
    {
      title: '发送时间',
      dataIndex: 'sent_at',
      key: 'sent_at',
      width: 180,
      render: (v: string | null) => v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-',
    },
    {
      title: '错误信息',
      dataIndex: 'error_message',
      key: 'error_message',
      ellipsis: true,
      render: (v: string | null) => v ? <Text type="danger" ellipsis>{v}</Text> : '-',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
    },
  ]

  return (
    <div className="stripe-page-container">
      <div className="stripe-page-header">
        <Title level={3} className="stripe-page-title">
          <MailOutlined className="stripe-page-icon" />
          每日运行报告
        </Title>
        {isSuperAdmin && (
          <Space>
            <Tooltip title="手动触发报告生成和发送">
              <Button
                type="primary"
                icon={<SendOutlined />}
                loading={triggering}
                onClick={handleTrigger}
                className="stripe-btn-primary"
              >
                手动发送
              </Button>
            </Tooltip>
          </Space>
        )}
      </div>

      {config?.report_enabled && (
        <Alert
          type="info"
          showIcon
          icon={<ClockCircleOutlined />}
          message={`定时推送已启用：每天 ${config.report_schedule_hour}:${String(config.report_schedule_minute).padStart(2, '0')} (Asia/Shanghai) 自动发送`}
          style={{ marginBottom: 16 }}
        />
      )}

      {triggerResult && (
        <Alert
          type={triggerResult.success ? 'success' : 'error'}
          showIcon
          icon={triggerResult.success ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
          message={triggerResult.message}
          closable
          onClose={() => setTriggerResult(null)}
          style={{ marginBottom: 16 }}
        />
      )}

      {isSuperAdmin && (
        <Card
          className="stripe-card report-config-section"
          title={<Space><SettingOutlined />邮件推送配置</Space>}
          loading={configLoading}
        >
          <Form
            form={configForm}
            layout="vertical"
            initialValues={config || {}}
            onFinish={handleSaveConfig}
          >
            <Alert
              type="info"
              showIcon
              icon={<InfoCircleOutlined />}
              message={
                <span>
                  SMTP 邮件服务器配置已提取至独立页面，每日报告和告警规则共用。
                  <a href="/admin/smtp-config" style={{ marginLeft: 8 }}>前往配置 →</a>
                </span>
              }
              style={{ marginBottom: 16 }}
            />

            <Divider orientation="left" plain>邮件内容</Divider>
<Form.Item label="收件人" name="report_recipients" rules={[{ required: true, message: '请输入收件人' }]}>
                  <Input placeholder="admin1@example.com, admin2@example.com" />
                </Form.Item>
                <div className="smtp-password-hint"><InfoCircleOutlined /> 多个收件人用逗号分隔</div>
                <Form.Item label="抄送" name="report_cc_recipients">
                  <Input placeholder="cc1@example.com, cc2@example.com" />
                </Form.Item>
                <Form.Item label="邮件主题模板" name="report_subject_template">
                  <Input placeholder="vLLM Ascend 运行报告 - {date}" />
                </Form.Item>
                <div className="smtp-password-hint"><InfoCircleOutlined /> {'{date}'} 会替换为报告日期</div>

            <Divider />
            <Space>
              <Button type="primary" htmlType="submit" loading={saving} icon={<SettingOutlined />}>
                保存配置
              </Button>
              <Button onClick={() => configForm.resetFields()}>
                重置
              </Button>
            </Space>
          </Form>
        </Card>
      )}

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={isSuperAdmin ? 14 : 24}>
          <Card
            className="stripe-card"
            title={<Space><HistoryOutlined />发送历史</Space>}
            extra={<Badge count={historyData?.total || 0} style={{ backgroundColor: '#635bff' }} />}
          >
            <Table
              className="report-history-table"
              dataSource={historyData?.items || []}
              columns={historyColumns}
              rowKey="id"
              loading={historyLoading}
              size="small"
              pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (t) => `共 ${t} 条` }}
            />
          </Card>
        </Col>
        {isSuperAdmin && (
          <Col span={10}>
            <Space direction="vertical" style={{ width: '100%' }} size={16}>
              <Card className="stripe-card" title={<Space><SendOutlined />手动触发</Space>} size="small">
                <Form layout="inline">
                  <Form.Item label="报告日期" style={{ flex: 1 }}>
                    <Input
                      placeholder="留空则默认昨天，格式 YYYY-MM-DD"
                      value={triggerDate}
                      onChange={(e) => setTriggerDate(e.target.value)}
                    />
                  </Form.Item>
                  <Form.Item>
                    <Button
                      type="primary"
                      icon={<SendOutlined />}
                      loading={triggering}
                      onClick={handleTrigger}
                    >
                      发送
                    </Button>
                  </Form.Item>
                </Form>
                <div className="smtp-password-hint" style={{ marginTop: 8 }}>
                  <InfoCircleOutlined /> 手动触发会立即生成报告并发送邮件
                </div>
              </Card>
              {renderLatestReport()}
            </Space>
          </Col>
        )}
      </Row>
    </div>
  )
}

export default DailyReportConfigPage