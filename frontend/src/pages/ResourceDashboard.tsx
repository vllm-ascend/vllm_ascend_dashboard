import { useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import {
  ClusterResourceSummary,
  ResourcePodInfo,
  ResourceQuantity,
  getEnabledResourceClusters,
  getResourceDashboard,
} from '../services/resourceDashboard'

const { Title, Text } = Typography

const formatCpu = (value: number) => `${value.toFixed(2)} 核`
const formatMemory = (bytes: number) => `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GiB`
const formatNpu = (value: number) => `${value.toFixed(0)} 卡`

const percent = (used: number, total: number) => (total > 0 ? Math.min((used / total) * 100, 100) : 0)

function ResourceUsage({ summary }: { summary: ClusterResourceSummary }) {
  return (
    <Space direction="vertical" style={{ width: '100%' }} size="small">
      <div>
        <Text>CPU {formatCpu(summary.used.cpu_cores)} / {formatCpu(summary.total.cpu_cores)}</Text>
        <Progress percent={percent(summary.used.cpu_cores, summary.total.cpu_cores)} size="small" />
      </div>
      <div>
        <Text>内存 {formatMemory(summary.used.memory_bytes)} / {formatMemory(summary.total.memory_bytes)}</Text>
        <Progress percent={percent(summary.used.memory_bytes, summary.total.memory_bytes)} size="small" />
      </div>
      <div>
        <Text>NPU {formatNpu(summary.used.npu)} / {formatNpu(summary.total.npu)}</Text>
        <Progress percent={percent(summary.used.npu, summary.total.npu)} size="small" />
      </div>
    </Space>
  )
}

function QuantityStats({ title, quantity, formatter }: { title: string; quantity: ResourceQuantity; formatter: (value: number) => string }) {
  const key = title === 'CPU' ? 'cpu_cores' : title === '内存' ? 'memory_bytes' : 'npu'
  return (
    <Card>
      <Statistic title={`${title} 总量`} value={formatter(quantity[key])} />
    </Card>
  )
}

function PodTable({ data }: { data: ResourcePodInfo[] }) {
  return (
    <Table<ResourcePodInfo>
      rowKey={(record) => `${record.cluster_id}-${record.namespace}-${record.name}`}
      dataSource={data}
      pagination={{ pageSize: 10, showSizeChanger: true }}
      scroll={{ x: 1300 }}
      columns={[
        { title: '集群', dataIndex: 'cluster_name', width: 140 },
        { title: 'Namespace', dataIndex: 'namespace', width: 140 },
        { title: 'Pod', dataIndex: 'name', width: 260 },
        {
          title: '状态',
          width: 120,
          render: (_, record) => <Tag color={record.phase === 'Running' ? 'green' : record.phase === 'Failed' ? 'red' : 'blue'}>{record.phase}</Tag>,
        },
        { title: 'Node', dataIndex: 'node_name', width: 180 },
        { title: 'CPU Request', render: (_, record) => formatCpu(record.requests.cpu_cores), width: 130 },
        { title: '内存 Request', render: (_, record) => formatMemory(record.requests.memory_bytes), width: 140 },
        { title: 'NPU Request', render: (_, record) => formatNpu(record.requests.npu), width: 120 },
        { title: '创建时间', render: (_, record) => record.created_at ? dayjs(record.created_at).format('YYYY-MM-DD HH:mm:ss') : '-', width: 180 },
        { title: '开始时间', render: (_, record) => record.started_at ? dayjs(record.started_at).format('YYYY-MM-DD HH:mm:ss') : '-', width: 180 },
        { title: '结束时间', render: (_, record) => record.finished_at ? dayjs(record.finished_at).format('YYYY-MM-DD HH:mm:ss') : '-', width: 180 },
        { title: '耗时', render: (_, record) => record.duration_seconds ? `${Math.round(record.duration_seconds / 60)} 分钟` : '-', width: 100 },
        {
          title: 'Labels',
          render: (_, record) => Object.entries(record.labels || {}).slice(0, 4).map(([key, value]) => <Tag key={key}>{key}={value}</Tag>),
          width: 260,
        },
      ]}
    />
  )
}

function ResourceDashboard() {
  const [selectedClusters, setSelectedClusters] = useState<number[]>([])
  const [labelSelector, setLabelSelector] = useState('')
  const [appliedFilters, setAppliedFilters] = useState({ clusterIds: [] as number[], labelSelector: '' })

  const { data: clusters = [] } = useQuery({
    queryKey: ['resource-clusters-enabled'],
    queryFn: getEnabledResourceClusters,
  })

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['resource-dashboard', appliedFilters],
    queryFn: () => getResourceDashboard({
      cluster_ids: appliedFilters.clusterIds.length ? appliedFilters.clusterIds : undefined,
      label_selector: appliedFilters.labelSelector || undefined,
      include_pods: true,
    }),
    refetchInterval: 60000,
  })

  const clusterOptions = useMemo(() => clusters.map(cluster => ({ label: cluster.name, value: cluster.id })), [clusters])

  const applyFilters = () => {
    setAppliedFilters({ clusterIds: selectedClusters, labelSelector: labelSelector.trim() })
  }

  const resetFilters = () => {
    setSelectedClusters([])
    setLabelSelector('')
    setAppliedFilters({ clusterIds: [], labelSelector: '' })
  }

  return (
    <div className="stripe-page-container">
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <Title level={2}>资源看板</Title>
            <Text type="secondary">查看多个 Kubernetes 资源池的 CPU、内存和 NPU 分配情况</Text>
          </div>
          <Space>
            {data?.generated_at && <Text type="secondary">更新时间：{dayjs(data.generated_at).format('YYYY-MM-DD HH:mm:ss')}</Text>}
            <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isFetching}>刷新</Button>
          </Space>
        </div>

        <Card>
          <Row gutter={[16, 16]}>
            <Col xs={24} md={8}>
              <Text>集群</Text>
              <Select mode="multiple" allowClear placeholder="默认全部启用集群" options={clusterOptions} value={selectedClusters} onChange={setSelectedClusters} style={{ width: '100%', marginTop: 8 }} />
            </Col>
            <Col xs={24} md={8}>
              <Text>Namespace</Text>
              <div style={{ marginTop: 8 }}><Tag color="blue">vllm-project</Tag></div>
            </Col>
            <Col xs={24} md={8}>
              <Text>Label Selector</Text>
              <Input placeholder="app=vllm,team=infra" value={labelSelector} onChange={event => setLabelSelector(event.target.value)} style={{ marginTop: 8 }} />
            </Col>
            <Col span={24}>
              <Space>
                <Button type="primary" onClick={applyFilters}>应用筛选</Button>
                <Button onClick={resetFilters}>重置</Button>
              </Space>
            </Col>
          </Row>
        </Card>

        {error && <Alert type="error" showIcon message="资源看板加载失败" description={(error as Error).message} />}

        {!isLoading && !data && <Empty description="暂无资源数据" />}

        {data && (
          <>
            <Row gutter={[16, 16]}>
              <Col xs={24} md={8}><QuantityStats title="CPU" quantity={data.overall.total} formatter={formatCpu} /></Col>
              <Col xs={24} md={8}><QuantityStats title="内存" quantity={data.overall.total} formatter={formatMemory} /></Col>
              <Col xs={24} md={8}><QuantityStats title="NPU" quantity={data.overall.total} formatter={formatNpu} /></Col>
              <Col xs={24} md={8}><Card><Statistic title="运行实例" value={data.overall.running_instances} /></Card></Col>
              <Col xs={24} md={8}><Card><Statistic title="执行中 Pod" value={data.overall.executing_pods_count} /></Card></Col>
              <Col xs={24} md={8}><Card><Statistic title="已执行 Pod" value={data.overall.executed_pods_count} /></Card></Col>
            </Row>

            <Card title="总资源使用情况">
              <ResourceUsage summary={data.overall} />
            </Card>

            <Row gutter={[16, 16]}>
              {data.clusters.map(summary => (
                <Col xs={24} lg={12} xl={8} key={summary.cluster_id}>
                  <Card title={summary.cluster_name} extra={summary.error ? <Tag color="red">异常</Tag> : <Tag color="green">正常</Tag>}>
                    {summary.error ? (
                      <Alert type="error" showIcon message="集群查询失败" description={summary.error} />
                    ) : (
                      <Space direction="vertical" style={{ width: '100%' }}>
                        <ResourceUsage summary={summary} />
                        <Space wrap>
                          <Tag>运行实例 {summary.running_instances}</Tag>
                          <Tag>执行中 {summary.executing_pods_count}</Tag>
                          <Tag>已执行 {summary.executed_pods_count}</Tag>
                        </Space>
                      </Space>
                    )}
                  </Card>
                </Col>
              ))}
            </Row>

            <Card title="Pod 信息">
              <Tabs
                items={[
                  { key: 'executing', label: `执行中 Pod (${data.executing_pods.length})`, children: <PodTable data={data.executing_pods} /> },
                  { key: 'executed', label: `已执行 Pod (${data.executed_pods.length})`, children: <PodTable data={data.executed_pods} /> },
                ]}
              />
            </Card>
          </>
        )}
      </Space>
    </div>
  )
}

export default ResourceDashboard
