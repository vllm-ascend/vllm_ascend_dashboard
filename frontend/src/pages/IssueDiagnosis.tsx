import {
  Card,
  Form,
  Select,
  Input,
  Button,
  Space,
  Alert,
  Typography,
  Upload,
  Tabs,
  Divider,
} from 'antd'
import {
  RobotOutlined,
  CopyOutlined,
  DownloadOutlined,
  SearchOutlined,
  UploadOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import StreamMarkdownRenderer from '../components/StreamMarkdownRenderer'
import { useIssueDiagnosis } from '../hooks/useIssueDiagnosis'

const { Title, Text } = Typography

function IssueDiagnosis() {
  const {
    dataSourceType,
    prNumber,
    selectedJobId,
    userPrompt,
    logContent,
    isStreaming,
    streamContent,
    meta,
    summary,
    error,
    ciJobOptions,
    loadingJobs,
    handleDataSourceTypeChange,
    setPrNumber,
    setSelectedJobId,
    setUserPrompt,
    setLogContent,
    handleStartDiagnosis,
    handleCopy,
    handleExport,
    handleReset,
    handleLogFileUpload,
    clearError,
  } = useIssueDiagnosis()

  return (
    <div className="stripe-ci-page">
      <div className="stripe-page-header">
        <Title level={3} className="stripe-page-title">
          <SearchOutlined style={{ marginRight: 8 }} />
          问题自动定位
        </Title>
        <Text className="stripe-page-description">
          输入 PR 编号或选择 Nightly Job，AI 智能分析问题根因并给出改进建议
        </Text>
      </div>

      <div style={{ display: 'flex', gap: 24, marginTop: 16 }}>
        <Card
          title="诊断配置"
          style={{ width: 420, flexShrink: 0 }}
          extra={
            streamContent ? (
              <Space size="small">
                <Button icon={<CopyOutlined />} size="small" onClick={handleCopy}>复制</Button>
                <Button icon={<DownloadOutlined />} size="small" onClick={handleExport}>导出</Button>
                <Button size="small" onClick={handleReset}>重置</Button>
              </Space>
            ) : null
          }
        >
          <Form layout="vertical">
            <Form.Item label="诊断类型">
              <Select
                value={dataSourceType}
                onChange={handleDataSourceTypeChange}
                options={[
                  { label: 'PR 流水线诊断', value: 'pr_pipeline' },
                  { label: 'Nightly Job 失败诊断', value: 'ci_job' },
                  { label: '手动输入', value: 'manual' },
                ]}
              />
            </Form.Item>

            {dataSourceType === 'pr_pipeline' && (
              <Form.Item label="PR 编号">
                <Input
                  type="number"
                  value={prNumber ?? ''}
                  onChange={(e) => setPrNumber(e.target.value ? Number(e.target.value) : null)}
                  placeholder="请输入 PR 编号，如 154"
                  size="large"
                />
              </Form.Item>
            )}

            {dataSourceType === 'ci_job' && (
              <Form.Item label="选择 Nightly Job">
                <Select
                  value={selectedJobId}
                  onChange={setSelectedJobId}
                  loading={loadingJobs}
                  placeholder="请选择一个失败的 Job"
                  showSearch
                  optionFilterProp="label"
                  options={ciJobOptions.map(j => ({
                    value: j.job_id,
                    label: `#${j.job_id} ${j.workflow_name} - ${j.job_name}`,
                  }))}
                />
              </Form.Item>
            )}

            {dataSourceType !== 'pr_pipeline' && (
              <>
                <Divider orientation="left" style={{ marginTop: 8, marginBottom: 12 }}>
                  <Space size={4}>
                    <FileTextOutlined />
                    <span style={{ fontSize: 13 }}>提示词与日志</span>
                  </Space>
                </Divider>

                <Tabs
                  type="card"
                  size="small"
                  items={[
                    {
                      key: 'prompt',
                      label: '提示词',
                      children: (
                        <Input.TextArea
                          value={userPrompt}
                          onChange={(e) => setUserPrompt(e.target.value)}
                          placeholder="输入补充提示词，描述你遇到的问题或你想了解的方向..."
                          rows={6}
                          maxLength={4000}
                          showCount
                        />
                      ),
                    },
                    {
                      key: 'log',
                      label: '日志提交',
                      children: (
                        <Space direction="vertical" style={{ width: '100%' }} size="middle">
                          <Upload
                            accept=".log,.txt,.json,.yaml,.yml,.xml,.csv"
                            maxCount={1}
                            showUploadList={false}
                            beforeUpload={handleLogFileUpload}
                          >
                            <Button icon={<UploadOutlined />} block>
                              上传日志文件
                            </Button>
                          </Upload>
                          <Input.TextArea
                            value={logContent}
                            onChange={(e) => setLogContent(e.target.value)}
                            placeholder="或直接粘贴日志内容..."
                            rows={6}
                            maxLength={50000}
                            showCount
                          />
                          {logContent && (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              已输入 {logContent.length} 字符
                            </Text>
                          )}
                        </Space>
                      ),
                    },
                  ]}
                />
              </>
            )}

            <Form.Item style={{ marginTop: 16 }}>
              <Button
                type="primary"
                icon={<RobotOutlined />}
                onClick={handleStartDiagnosis}
                loading={isStreaming}
                disabled={isStreaming}
                block
                size="large"
              >
                {isStreaming ? '诊断中...' : '开始诊断'}
              </Button>
            </Form.Item>
          </Form>

          {error && (
            <Alert
              message="诊断失败"
              description={error}
              type="error"
              showIcon
              closable
              onClose={clearError}
              style={{ marginTop: 8 }}
            />
          )}
        </Card>

        <Card title="AI 分析结果" style={{ flex: 1, minHeight: 600 }}>
          <StreamMarkdownRenderer
            content={streamContent}
            isStreaming={isStreaming}
            meta={meta}
            summary={summary}
          />
        </Card>
      </div>
    </div>
  )
}

export default IssueDiagnosis
