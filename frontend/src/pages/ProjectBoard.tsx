import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card,
  Table,
  Space,
  Typography,
  Tag,
  Button,
  Row,
  Col,
  Descriptions,
  Input,
  Select,
  Modal,
  Form,
  message,
  Tabs,
  List,
  Timeline,
  Divider,
  Tooltip,
  Alert,
  Spin,
  Empty,
} from 'antd'
import {
  GithubOutlined,
  DockerOutlined,
  LinkOutlined,
  CopyOutlined,
  ReloadOutlined,
  MergeOutlined,
  SwapOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  getReleases,
  getMainVersions,
  getModelSupportMatrix,
  compareTags,
  rerunPRCI,
  forceMergePR,
  getPRCIStatus,
  type ReleaseInfo,
  type WorkflowRun,
  type VllmVersionInfo,
  type ModelSupportEntry,
  type CommitInfo,
  type TagComparisonResult,
} from '../services/projectDashboard'
import PROperations from '../components/PROperations'
import { useCurrentUser } from '../hooks/useCurrentUser'
import './ProjectBoard.css'

const { Text, Title, Paragraph } = Typography
const { Search } = Input

interface ModelSupportEntryWithKey extends ModelSupportEntry {
  key: string
}

function ProjectBoard() {
  const navigate = useNavigate()
  const { data: currentUser } = useCurrentUser()
  const isLoggedIn = !!localStorage.getItem('access_token')
  const isAdmin = currentUser?.role === 'admin' || currentUser?.role === 'super_admin'

  // 发布版本状态
  const [releases, setReleases] = useState<ReleaseInfo[]>([])
  const [releasesLoading, setReleasesLoading] = useState(false)

  // 主分支版本状态
  const [mainVersions, setMainVersions] = useState<VllmVersionInfo | null>(null)
  const [versionsLoading, setVersionsLoading] = useState(false)

  // 模型支持矩阵状态
  const [modelMatrix, setModelMatrix] = useState<ModelSupportEntryWithKey[]>([])
  const [featureColumns, setFeatureColumns] = useState<any[]>([])
  const [matrixLoading, setMatrixLoading] = useState(false)
  const [modelSearchText, setModelSearchText] = useState('')
  const [modelSeriesFilter, setModelSeriesFilter] = useState<string[]>([])
  const [modelStatusFilter, setStatusFilter] = useState<string[]>([])

  // Tag 对比状态
  const [compareModalVisible, setCompareModalVisible] = useState(false)
  const [compareForm] = Form.useForm()
  const [compareLoading, setCompareLoading] = useState(false)
  const [compareResult, setCompareResult] = useState<TagComparisonResult | null>(null)
  const [availableTags, setAvailableTags] = useState<string[]>([])

  // 加载发布版本
  useEffect(() => {
    const loadReleases = async () => {
      setReleasesLoading(true)
      try {
        // Load recommended releases for the table (latest 1 stable + 1 pre-release)
        const recommendedData = await getReleases(true)
        setReleases(recommendedData.releases)
        
        // Load all tags for comparison dropdown
        const allTagsData = await getReleases(false)
        const allTags = allTagsData.releases.map(r => r.version)
        // Add "main" branch as an option for tag comparison
        setAvailableTags(['main', ...allTags])
        
        // 如果没有 tags，提示用户需要更新缓存
        if (allTags.length === 0 && isAdmin) {
          message.warning('未找到任何 release tags，请管理员在"项目看板配置"中更新本地 Git 仓库缓存')
        }
      } catch (error: any) {
        message.error('加载发布版本失败：' + (error.response?.data?.detail || error.message))
      } finally {
        setReleasesLoading(false)
      }
    }
    loadReleases()
  }, [])

  // 加载主分支版本
  useEffect(() => {
    const loadVersions = async () => {
      setVersionsLoading(true)
      try {
        const data = await getMainVersions()
        setMainVersions(data)
      } catch (error: any) {
        message.error('加载版本信息失败：' + (error.response?.data?.detail || error.message))
      } finally {
        setVersionsLoading(false)
      }
    }
    loadVersions()
  }, [])

  // 加载模型支持矩阵
  useEffect(() => {
    const loadMatrix = async () => {
      setMatrixLoading(true)
      try {
        const data = await getModelSupportMatrix()
        // 加载特性列配置
        if (data.featureColumns) {
          setFeatureColumns(data.featureColumns)
        }
        // 加载模型数据
        if (data.entries) {
          const entriesWithKey = data.entries.map((e: ModelSupportEntry, idx: number) => ({ ...e, key: `${idx}-${e.model_name}` }))
          setModelMatrix(entriesWithKey)
        }
      } catch (error: any) {
        message.error('加载模型矩阵失败：' + (error.response?.data?.detail || error.message))
      } finally {
        setMatrixLoading(false)
      }
    }
    loadMatrix()
  }, [])

  // 复制到剪贴板
  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      message.success('已复制到剪贴板')
    } catch (error) {
      message.error('复制失败')
    }
  }

  // Tag 对比
  const handleCompareTags = async (values: { base_tag: string; head_tag: string }) => {
    setCompareLoading(true)
    try {
      const result = await compareTags(values.base_tag, values.head_tag)
      setCompareResult(result)
      // 滚动到结果区域
      setTimeout(() => {
        document.getElementById('compare-result')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 100)
    } catch (error: any) {
      message.error('对比 Tag 失败：' + (error.response?.data?.detail || error.message))
    } finally {
      setCompareLoading(false)
    }
  }

  // 处理 PR 操作（已在 PROperations 组件中实现）

  // 模型矩阵表格列（只读）
  const modelColumns = [
    {
      title: '模型名称',
      dataIndex: 'model_name',
      key: 'model_name',
      width: 200,
      sorter: (a: any, b: any) => a.model_name.localeCompare(b.model_name),
      filteredValue: modelSeriesFilter.length > 0 ? modelSeriesFilter : null,
      onFilter: (value: any, record: any) => record.series === value,
    },
    {
      title: '系列',
      dataIndex: 'series',
      key: 'series',
      width: 150,
      filters: Array.from(new Set(modelMatrix.map(m => m.series))).map(s => ({ text: s, value: s })),
      onFilter: (value: any, record: any) => record.series === value,
    },
    {
      title: '支持状态',
      dataIndex: 'support',
      key: 'support',
      width: 120,
      filters: [
        { text: '✅ 支持', value: 'supported' },
        { text: '🔵 实验中', value: 'experimental' },
        { text: '❌ 不支持', value: 'not_supported' },
        { text: '🟡 未测试', value: 'untested' },
      ],
      onFilter: (value: any, record: any) => record.support === value,
      render: (support: string) => {
        const statusConfig: Record<string, { color: string; text: string; icon: string }> = {
          supported: { color: 'green', text: '支持', icon: '✅' },
          experimental: { color: 'orange', text: '实验中', icon: '🔵' },
          not_supported: { color: 'red', text: '不支持', icon: '❌' },
          untested: { color: 'default', text: '未测试', icon: '🟡' },
        }
        const config = statusConfig[support] || statusConfig.supported
        return <Tag color={config.color}>{config.icon} {config.text}</Tag>
      },
    },
    {
      title: '支持硬件',
      dataIndex: 'supported_hardware',
      key: 'supported_hardware',
      width: 120,
      render: (hardware: string | null) => hardware || '-',
    },
    {
      title: '权重格式',
      dataIndex: 'weight_format',
      key: 'weight_format',
      width: 180,
      render: (format: string | null) => {
        if (!format) return '-'
        const formats = format.split('/').filter(Boolean)
        return formats.map(f => (
          <Tag key={f} color="blue" style={{ marginRight: 4, marginBottom: 4 }}>{f}</Tag>
        ))
      },
    },
    {
      title: 'KV Cache',
      dataIndex: 'kv_cache_type',
      key: 'kv_cache_type',
      width: 150,
      render: (cache: string | null) => {
        if (!cache) return '-'
        const caches = cache.split('/').filter(Boolean)
        return caches.map(c => (
          <Tag key={c} color="green" style={{ marginRight: 4, marginBottom: 4 }}>{c}</Tag>
        ))
      },
    },
    // 动态生成特性列（只读）
    ...featureColumns.map(col => ({
      title: col.title,
      dataIndex: col.key,
      key: col.key,
      width: col.width,
      render: (value: any) => {
        if (col.type === 'toggle') {
          return value ? '✅' : value === false ? '❌' : '-'
        } else if (col.type === 'multiSelect') {
          return value || '-'
        } else if (col.type === 'input') {
          return value || '-'
        }
        return '-'
      },
    })),
    {
      title: '文档',
      key: 'doc_link',
      dataIndex: 'doc_link',
      width: 100,
      render: (link: string | null) => {
        if (!link) return <Text type="secondary">-</Text>
        return (
          <Button
            type="link"
            size="small"
            href={link}
            target="_blank"
            rel="noopener noreferrer"
            icon={<LinkOutlined />}
          >
            官方教程
          </Button>
        )
      },
    },
    {
      title: '备注',
      dataIndex: 'note',
      key: 'note',
      width: 200,
      ellipsis: true,
      render: (note: string | null) => note || '-',
    },
  ]

  // 按搜索文本过滤模型矩阵
  const filteredModelMatrix = modelMatrix.filter(model => {
    const matchesSearch = model.model_name.toLowerCase().includes(modelSearchText.toLowerCase()) ||
                         model.series.toLowerCase().includes(modelSearchText.toLowerCase())
    return matchesSearch
  })

  // 发布版本表格列
  const releaseColumns = [
    {
      title: '版本',
      dataIndex: 'version',
      key: 'version',
      width: 250,
      sorter: (a: any, b: any) => a.version.localeCompare(b.version),
      render: (version: string, record: ReleaseInfo) => (
        <Space>
          <Text strong>{version}</Text>
          {!record.is_stable && <Tag color="orange">预发布版本</Tag>}
          {record.is_stable && <Tag color="green">稳定版</Tag>}
        </Space>
      ),
    },
    {
      title: '发布时间',
      dataIndex: 'published_at',
      key: 'published_at',
      width: 180,
      sorter: (a: any, b: any) => new Date(a.published_at).getTime() - new Date(b.published_at).getTime(),
      render: (date: string) => dayjs(date).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: 'Docker 拉取命令',
      key: 'docker_commands',
      render: (_: any, record: ReleaseInfo) => (
        <Space direction="vertical" size="small" style={{ width: '100%' }}>
          {Object.entries(record.docker_commands).map(([mirror, cmd]) => (
            <Space key={mirror} style={{ width: '100%' }}>
              <Tag color="blue">{mirror}</Tag>
              <Text code style={{ flex: 1, fontSize: 12 }}>{cmd}</Text>
              <Button
                type="text"
                size="small"
                icon={<CopyOutlined />}
                onClick={() => copyToClipboard(cmd)}
              />
            </Space>
          ))}
        </Space>
      ),
    },
  ]

  return (
    <div className="stripe-project-page">
      {/* 页面标题 */}
      <div className="stripe-page-header">
        <Title level={3} className="stripe-page-title">
          <GithubOutlined className="stripe-page-icon" />
          项目看板
        </Title>
        <Text className="stripe-page-description">
          vLLM Ascend 项目信息总览
        </Text>
      </div>

      <Tabs
          defaultActiveKey="releases"
        items={[
          {
            key: 'releases',
            label: (
              <Space>
                <DockerOutlined />
                发布版本与镜像
              </Space>
            ),
            children: (
              <Row gutter={[16, 16]}>
                {/* 主分支版本 */}
                <Col span={24}>
                  <Card
                    title="主分支的vLLM 版本"
                    loading={versionsLoading}
                  >
                    {mainVersions && (
                      <Descriptions column={2} bordered>
                        <Descriptions.Item label="vLLM 版本">
                          <Tag color="blue">{mainVersions.vllm_version === 'Unknown' ? '-' : mainVersions.vllm_version}</Tag>
                        </Descriptions.Item>
                        <Descriptions.Item label="vLLM Commit">
                          <Tag color="purple">{mainVersions.vllm_commit || '-'}</Tag>
                        </Descriptions.Item>
                        <Descriptions.Item label="最后更新" span={2}>
                          {dayjs(mainVersions.updated_at).format('YYYY-MM-DD HH:mm')}
                        </Descriptions.Item>
                      </Descriptions>
                    )}
                  </Card>
                </Col>

                {/* 发布版本表格 */}
                <Col span={24}>
                  <Card 
                    title="推荐版本"
                    extra={<Text type="secondary" style={{ fontSize: 12 }}>显示最新 1 个稳定版 + 1 个预发布版本</Text>}
                  >
                    <Table
                      columns={releaseColumns}
                      dataSource={releases}
                      loading={releasesLoading}
                      rowKey="version"
                      pagination={false}
                      scroll={{ x: 1000 }}
                    />
                  </Card>
                </Col>
              </Row>
            ),
          },
          {
            key: 'models',
            label: (
              <Space>
                <FileTextOutlined />
                模型支持矩阵
              </Space>
            ),
            children: (
              <Card>
                <div style={{ marginBottom: 16, display: 'flex', gap: 16 }}>
                  <Search
                    placeholder="搜索模型..."
                    value={modelSearchText}
                    onChange={(e) => setModelSearchText(e.target.value)}
                    style={{ width: 300 }}
                    allowClear
                  />
                </div>
                <Table
                  columns={modelColumns}
                  dataSource={filteredModelMatrix}
                  loading={matrixLoading}
                  pagination={{ pageSize: 20 }}
                  scroll={{ x: 800 }}
                  onChange={(pagination, filters) => {
                    if (filters.series) {
                      setModelSeriesFilter(filters.series as string[])
                    }
                    if (filters.status) {
                      setStatusFilter(filters.status as string[])
                    }
                  }}
                />
              </Card>
            ),
          },
          {
            key: 'compare',
            label: (
              <Space>
                <SwapOutlined />
                对比 Tag
              </Space>
            ),
            children: (
              <Card>
                {/* Tag 选择器 */}
                <Form
                  form={compareForm}
                  layout="inline"
                  onFinish={handleCompareTags}
                  style={{ marginBottom: 24 }}
                >
                  <Form.Item
                    name="base_tag"
                    label="基准 Tag"
                    rules={[{ required: true, message: '请选择基准 Tag' }]}
                  >
                    <Select
                      style={{ width: 200 }}
                      options={availableTags.map(tag => ({ label: tag, value: tag }))}
                      showSearch
                      filterOption={(input, option) =>
                        (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
                      }
                      placeholder="选择基准 Tag"
                    />
                  </Form.Item>
                  <Form.Item
                    name="head_tag"
                    label="目标 Tag"
                    rules={[{ required: true, message: '请选择目标 Tag' }]}
                  >
                    <Select
                      style={{ width: 200 }}
                      options={availableTags.map(tag => ({ label: tag, value: tag }))}
                      showSearch
                      filterOption={(input, option) =>
                        (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
                      }
                      placeholder="选择目标 Tag"
                    />
                  </Form.Item>
                  <Form.Item>
                    <Button
                      type="primary"
                      htmlType="submit"
                      icon={<SwapOutlined />}
                      loading={compareLoading}
                    >
                      对比
                    </Button>
                  </Form.Item>
                </Form>

                {compareResult && (
                  <div id="compare-result">
                    <Title level={4}>
                      对比：{compareResult.base_tag} → {compareResult.head_tag}
                    </Title>
                    <Descriptions bordered column={4} style={{ marginBottom: 24 }}>
                      <Descriptions.Item label="总提交数">
                        {compareResult.total_commits}
                      </Descriptions.Item>
                      <Descriptions.Item label="Bug 修复">
                        <Tag color="red">{compareResult.summary.BugFix}</Tag>
                      </Descriptions.Item>
                      <Descriptions.Item label="新功能">
                        <Tag color="green">{compareResult.summary.Feature}</Tag>
                      </Descriptions.Item>
                      <Descriptions.Item label="性能优化">
                        <Tag color="blue">{compareResult.summary.Performance}</Tag>
                      </Descriptions.Item>
                      <Descriptions.Item label="代码重构">
                        <Tag color="purple">{compareResult.summary.Refactor}</Tag>
                      </Descriptions.Item>
                      <Descriptions.Item label="文档">
                        <Tag color="orange">{compareResult.summary.Doc}</Tag>
                      </Descriptions.Item>
                      <Descriptions.Item label="测试">
                        <Tag color="gold">{compareResult.summary.Test}</Tag>
                      </Descriptions.Item>
                      <Descriptions.Item label="CI/CD">
                        <Tag color="cyan">{compareResult.summary.CI}</Tag>
                      </Descriptions.Item>
                      <Descriptions.Item label="其他">
                        <Tag color="default">{compareResult.summary.Misc}</Tag>
                      </Descriptions.Item>
                    </Descriptions>

                    <Tabs
                      items={[
                        {
                          key: 'bugfixes',
                          label: `Bug 修复 (${compareResult.bug_fixes.length})`,
                          children: (
                            <Timeline
                              items={compareResult.bug_fixes.map((commit: CommitInfo) => ({
                                key: commit.sha,
                                color: 'red',
                                children: (
                                  <div>
                                    <Text strong>{commit.title}</Text>
                                    <br />
                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                      {commit.author} • {dayjs(commit.date).format('YYYY-MM-DD')}
                                      {commit.pr_number && (
                                        <>
                                          {' '}• PR#{' '}
                                          <a
                                            href={`https://github.com/vllm-project/vllm-ascend/pull/${commit.pr_number}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                          >
                                            {commit.pr_number}
                                          </a>
                                        </>
                                      )}
                                    </Text>
                                  </div>
                                ),
                              }))}
                            />
                          ),
                        },
                        {
                          key: 'features',
                          label: `新功能 (${compareResult.features.length})`,
                          children: (
                            <Timeline
                              items={compareResult.features.map((commit: CommitInfo) => ({
                                key: commit.sha,
                                color: 'green',
                                children: (
                                  <div>
                                    <Text strong>{commit.title}</Text>
                                    <br />
                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                      {commit.author} • {dayjs(commit.date).format('YYYY-MM-DD')}
                                      {commit.pr_number && (
                                        <>
                                          {' '}• PR#{' '}
                                          <a
                                            href={`https://github.com/vllm-project/vllm-ascend/pull/${commit.pr_number}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                          >
                                            {commit.pr_number}
                                          </a>
                                        </>
                                      )}
                                    </Text>
                                  </div>
                                ),
                              }))}
                            />
                          ),
                        },
                        {
                          key: 'performance',
                          label: `性能优化 (${compareResult.performance_improvements.length})`,
                          children: (
                            <Timeline
                              items={compareResult.performance_improvements.map((commit: CommitInfo) => ({
                                key: commit.sha,
                                color: 'blue',
                                children: (
                                  <div>
                                    <Text strong>{commit.title}</Text>
                                    <br />
                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                      {commit.author} • {dayjs(commit.date).format('YYYY-MM-DD')}
                                      {commit.pr_number && (
                                        <>
                                          {' '}• PR#{' '}
                                          <a
                                            href={`https://github.com/vllm-project/vllm-ascend/pull/${commit.pr_number}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                          >
                                            {commit.pr_number}
                                          </a>
                                        </>
                                      )}
                                    </Text>
                                  </div>
                                ),
                              }))}
                            />
                          ),
                        },
                        {
                          key: 'refactors',
                          label: `代码重构 (${compareResult.refactors.length})`,
                          children: (
                            <Timeline
                              items={compareResult.refactors.map((commit: CommitInfo) => ({
                                key: commit.sha,
                                color: 'purple',
                                children: (
                                  <div>
                                    <Text strong>{commit.title}</Text>
                                    <br />
                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                      {commit.author} • {dayjs(commit.date).format('YYYY-MM-DD')}
                                      {commit.pr_number && (
                                        <>
                                          {' '}• PR#{' '}
                                          <a
                                            href={`https://github.com/vllm-project/vllm-ascend/pull/${commit.pr_number}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                          >
                                            {commit.pr_number}
                                          </a>
                                        </>
                                      )}
                                    </Text>
                                  </div>
                                ),
                              }))}
                            />
                          ),
                        },
                        {
                          key: 'docs',
                          label: `文档 (${compareResult.docs.length})`,
                          children: (
                            <Timeline
                              items={compareResult.docs.map((commit: CommitInfo) => ({
                                key: commit.sha,
                                color: 'orange',
                                children: (
                                  <div>
                                    <Text strong>{commit.title}</Text>
                                    <br />
                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                      {commit.author} • {dayjs(commit.date).format('YYYY-MM-DD')}
                                      {commit.pr_number && (
                                        <>
                                          {' '}• PR#{' '}
                                          <a
                                            href={`https://github.com/vllm-project/vllm-ascend/pull/${commit.pr_number}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                          >
                                            {commit.pr_number}
                                          </a>
                                        </>
                                      )}
                                    </Text>
                                  </div>
                                ),
                              }))}
                            />
                          ),
                        },
                        {
                          key: 'tests',
                          label: `测试 (${compareResult.tests.length})`,
                          children: (
                            <Timeline
                              items={compareResult.tests.map((commit: CommitInfo) => ({
                                key: commit.sha,
                                color: 'gold',
                                children: (
                                  <div>
                                    <Text strong>{commit.title}</Text>
                                    <br />
                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                      {commit.author} • {dayjs(commit.date).format('YYYY-MM-DD')}
                                      {commit.pr_number && (
                                        <>
                                          {' '}• PR#{' '}
                                          <a
                                            href={`https://github.com/vllm-project/vllm-ascend/pull/${commit.pr_number}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                          >
                                            {commit.pr_number}
                                          </a>
                                        </>
                                      )}
                                    </Text>
                                  </div>
                                ),
                              }))}
                            />
                          ),
                        },
                        {
                          key: 'ci',
                          label: `CI/CD (${compareResult.ci_changes.length})`,
                          children: (
                            <Timeline
                              items={compareResult.ci_changes.map((commit: CommitInfo) => ({
                                key: commit.sha,
                                color: 'cyan',
                                children: (
                                  <div>
                                    <Text strong>{commit.title}</Text>
                                    <br />
                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                      {commit.author} • {dayjs(commit.date).format('YYYY-MM-DD')}
                                      {commit.pr_number && (
                                        <>
                                          {' '}• PR#{' '}
                                          <a
                                            href={`https://github.com/vllm-project/vllm-ascend/pull/${commit.pr_number}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                          >
                                            {commit.pr_number}
                                          </a>
                                        </>
                                      )}
                                    </Text>
                                  </div>
                                ),
                              }))}
                            />
                          ),
                        },
                        {
                          key: 'misc',
                          label: `其他 (${compareResult.misc.length})`,
                          children: (
                            <Timeline
                              items={compareResult.misc.map((commit: CommitInfo) => ({
                                key: commit.sha,
                                color: 'default',
                                children: (
                                  <div>
                                    <Text strong>{commit.title}</Text>
                                    <br />
                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                      {commit.author} • {dayjs(commit.date).format('YYYY-MM-DD')}
                                      {commit.pr_number && (
                                        <>
                                          {' '}• PR#{' '}
                                          <a
                                            href={`https://github.com/vllm-project/vllm-ascend/pull/${commit.pr_number}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                          >
                                            {commit.pr_number}
                                          </a>
                                        </>
                                      )}
                                    </Text>
                                  </div>
                                ),
                              }))}
                            />
                          ),
                        },
                        {
                          key: 'all',
                          label: `所有提交 (${compareResult.commits.length})`,
                          children: (
                            <Timeline
                              items={compareResult.commits.map((commit: CommitInfo) => ({
                                key: commit.sha,
                                children: (
                                  <div>
                                    <Space>
                                      <Tag color={
                                        commit.category === 'BugFix' ? 'red' :
                                        commit.category === 'Feature' ? 'green' :
                                        commit.category === 'Performance' ? 'blue' :
                                        commit.category === 'Refactor' ? 'purple' :
                                        commit.category === 'Doc' ? 'orange' :
                                        commit.category === 'Test' ? 'gold' :
                                        commit.category === 'CI' ? 'cyan' : 'default'
                                      }>
                                        {commit.category === 'BugFix' ? 'Bug 修复' :
                                         commit.category === 'Feature' ? '新功能' :
                                         commit.category === 'Performance' ? '性能优化' :
                                         commit.category === 'Refactor' ? '代码重构' :
                                         commit.category === 'Doc' ? '文档' :
                                         commit.category === 'Test' ? '测试' :
                                         commit.category === 'CI' ? 'CI/CD' : '其他'}
                                      </Tag>
                                      <Text strong>{commit.title}</Text>
                                    </Space>
                                    <br />
                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                      {commit.author} • {dayjs(commit.date).format('YYYY-MM-DD')}
                                      {commit.pr_number && (
                                        <>
                                          {' '}• PR#{' '}
                                          <a
                                            href={`https://github.com/vllm-project/vllm-ascend/pull/${commit.pr_number}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                          >
                                            {commit.pr_number}
                                          </a>
                                        </>
                                      )}
                                    </Text>
                                  </div>
                                ),
                              }))}
                            />
                          ),
                        },
                      ]}
                    />
                  </div>
                )}
              </Card>
            ),
          },
          ...(isAdmin ? [{
            key: 'pr-actions',
            label: (
              <Space>
                <MergeOutlined />
                PR 操作
              </Space>
            ),
            children: (
              <PROperations isAdmin={isAdmin} />
            ),
          }] : []),
        ]}
      />
    </div>
  )
}

export default ProjectBoard
