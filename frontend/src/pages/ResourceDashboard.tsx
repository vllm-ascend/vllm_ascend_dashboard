import { useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Drawer,
  Empty,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import {
  ClusterResourceSummary,
  ResourceNodeInfo,
  ResourcePodInfo,
  ResourceQuantity,
  getEnabledResourceClusters,
  getResourceDashboard,
} from '../services/resourceDashboard'

const { Title, Text } = Typography

const formatCpu = (value: number) => `${value.toFixed(2)} 核`
const formatMemory = (bytes: number) => `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GiB`
const formatNpu = (value: number) => `${value.toFixed(0)} 卡`

const percent = (used: number, total: number) => (total > 0 ? Math.round(Math.min((used / total) * 100, 100)) : 0)
const usageColor = (value: number) => (value >= 90 ? '#ff4d4f' : value >= 50 ? '#1677ff' : '#52c41a')

function ResourceUsage({ summary }: { summary: ClusterResourceSummary }) {
  const cpuPercent = percent(summary.used.cpu_cores, summary.total.cpu_cores)
  const memoryPercent = percent(summary.used.memory_bytes, summary.total.memory_bytes)
  const npuPercent = percent(summary.used.npu, summary.total.npu)

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="small">
      <div>
        <Text>CPU {formatCpu(summary.used.cpu_cores)} / {formatCpu(summary.total.cpu_cores)}</Text>
        <Progress percent={cpuPercent} strokeColor={usageColor(cpuPercent)} status="normal" size="small" />
      </div>
      <div>
        <Text>内存 {formatMemory(summary.used.memory_bytes)} / {formatMemory(summary.total.memory_bytes)}</Text>
        <Progress percent={memoryPercent} strokeColor={usageColor(memoryPercent)} status="normal" size="small" />
      </div>
      <div>
        <Text>NPU {formatNpu(summary.used.npu)} / {formatNpu(summary.total.npu)}</Text>
        <Progress percent={npuPercent} strokeColor={usageColor(npuPercent)} status="normal" size="small" />
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

function NodeResourceTable({ data }: { data: ResourceNodeInfo[] }) {
  const visibleNodes = data.filter(record => record.total.npu > 0)
  const renderUsage = (used: number, total: number, available: number, formatter: (value: number) => string) => {
    const value = percent(used, total)
    return (
      <Space direction="vertical" size={2} style={{ width: '100%' }}>
        <Text>{formatter(used)} / {formatter(total)}</Text>
        <Progress percent={value} strokeColor={usageColor(value)} status="normal" size="small" />
        <Text type="secondary">可用 {formatter(available)}</Text>
      </Space>
    )
  }

  return (
    <Table<ResourceNodeInfo>
      rowKey="node_name"
      dataSource={visibleNodes}
      pagination={false}
      scroll={{ x: 900 }}
      columns={[
        { title: 'Node', dataIndex: 'node_name', width: 220 },
        { title: 'CPU', render: (_, record) => renderUsage(record.used.cpu_cores, record.total.cpu_cores, record.available.cpu_cores, formatCpu), width: 220 },
        { title: '内存', render: (_, record) => renderUsage(record.used.memory_bytes, record.total.memory_bytes, record.available.memory_bytes, formatMemory), width: 220 },
        { title: 'NPU', render: (_, record) => renderUsage(record.used.npu, record.total.npu, record.available.npu, formatNpu), width: 180 },
        { title: '执行中 Pod', dataIndex: 'executing_pods_count', width: 120 },
      ]}
    />
  )
}

function PodTable({ data }: { data: ResourcePodInfo[] }) {
  const [pageSize, setPageSize] = useState(10)

  return (
    <Table<ResourcePodInfo>
      rowKey={(record) => `${record.cluster_id}-${record.namespace}-${record.name}`}
      dataSource={data}
      pagination={{
        pageSize,
        showSizeChanger: true,
        onShowSizeChange: (_, size) => setPageSize(size),
        onChange: (_, size) => setPageSize(size),
      }}
      scroll={{ x: 980 }}
      columns={[
        { title: '集群', dataIndex: 'cluster_name', width: 140 },
        { title: 'Pod', dataIndex: 'name', width: 260 },
        {
          title: '状态',
          width: 120,
          render: (_, record) => <Tag color={record.phase === 'Running' ? 'green' : record.phase === 'Failed' ? 'red' : 'blue'}>{record.phase}</Tag>,
          filters: Array.from(new Set(data.map(record => record.phase).filter((phase): phase is string => Boolean(phase))))
            .sort()
            .map(value => ({ text: value, value })),
          onFilter: (value, record) => record.phase === value,
        },
        { title: 'CPU Request', render: (_, record) => formatCpu(record.requests.cpu_cores), width: 130 },
        { title: '内存 Request', render: (_, record) => formatMemory(record.requests.memory_bytes), width: 140 },
        {
          title: 'NPU Request',
          render: (_, record) => formatNpu(record.requests.npu),
          width: 120,
          filters: Array.from(new Set(data.map(record => record.requests.npu)))
            .sort((left, right) => left - right)
            .map(value => ({ text: formatNpu(value), value })),
          onFilter: (value, record) => record.requests.npu === Number(value),
        },
        { title: '创建时间', render: (_, record) => record.created_at ? dayjs(record.created_at).format('YYYY-MM-DD HH:mm:ss') : '-', width: 180 },
        { title: '开始时间', render: (_, record) => record.started_at ? dayjs(record.started_at).format('YYYY-MM-DD HH:mm:ss') : '-', width: 180 },
        { title: '耗时', render: (_, record) => record.duration_seconds ? `${Math.round(record.duration_seconds / 60)} 分钟` : '-', width: 100 },
        { title: 'Node', dataIndex: 'node_name', width: 180 },
      ]}
    />
  )
}

function ResourceDashboard() {
  const [selectedClusters, setSelectedClusters] = useState<number[]>([])
  const [appliedFilters, setAppliedFilters] = useState({ clusterIds: [] as number[] })
  const [selectedClusterSummary, setSelectedClusterSummary] = useState<ClusterResourceSummary | null>(null)

  const { data: clusters = [] } = useQuery({
    queryKey: ['resource-clusters-enabled'],
    queryFn: getEnabledResourceClusters,
  })

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['resource-dashboard', appliedFilters],
    queryFn: () => getResourceDashboard({
      cluster_ids: appliedFilters.clusterIds.length ? appliedFilters.clusterIds : undefined,
      include_pods: true,
    }),
    refetchInterval: 60000,
  })

  const clusterOptions = useMemo(() => clusters.map(cluster => ({ label: cluster.name, value: cluster.id })), [clusters])

  const applyFilters = () => {
    setAppliedFilters({ clusterIds: selectedClusters })
  }

  const resetFilters = () => {
    setSelectedClusters([])
    setAppliedFilters({ clusterIds: [] })
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

        <Card size="small">
          <Space wrap align="end" size="middle" style={{ width: '100%' }}>
            <div style={{ minWidth: 360, flex: 1 }}>
              <Text>集群</Text>
              <Select mode="multiple" allowClear maxTagCount="responsive" placeholder="默认全部启用集群" options={clusterOptions} value={selectedClusters} onChange={setSelectedClusters} style={{ width: '100%', marginTop: 8 }} />
            </div>
            <Space>
              <Button type="primary" onClick={applyFilters}>应用筛选</Button>
              <Button onClick={resetFilters}>重置</Button>
            </Space>
          </Space>
        </Card>

        {error && <Alert type="error" showIcon message="资源看板加载失败" description={(error as Error).message} />}

        {!isLoading && !data && <Empty description="暂无资源数据" />}

        {data && (
          <>
            <Row gutter={[16, 16]}>
              <Col xs={24} md={8}><QuantityStats title="CPU" quantity={data.overall.total} formatter={formatCpu} /></Col>
              <Col xs={24} md={8}><QuantityStats title="内存" quantity={data.overall.total} formatter={formatMemory} /></Col>
              <Col xs={24} md={8}><QuantityStats title="NPU" quantity={data.overall.total} formatter={formatNpu} /></Col>
              <Col xs={24} md={12}><Card><Statistic title="运行实例" value={data.overall.running_instances} /></Card></Col>
              <Col xs={24} md={12}><Card><Statistic title="执行中 Pod" value={data.overall.executing_pods_count} /></Card></Col>
            </Row>

            <Card title="总资源使用情况">
              <ResourceUsage summary={data.overall} />
            </Card>

            <Row gutter={[16, 16]}>
              {data.clusters.map(summary => (
                <Col xs={24} lg={12} xl={8} key={summary.cluster_id}>
                  <Card
                    hoverable
                    title={summary.cluster_name}
                    extra={summary.error ? <Tag color="red">异常</Tag> : <Tag color="green">正常</Tag>}
                    onClick={() => setSelectedClusterSummary(summary)}
                    style={{ cursor: 'pointer' }}
                  >
                    {summary.error ? (
                      <Alert type="error" showIcon message="集群查询失败" description={summary.error} />
                    ) : (
                      <Space direction="vertical" style={{ width: '100%' }}>
                        <ResourceUsage summary={summary} />
                        <Space wrap>
                          <Tag>运行实例 {summary.running_instances}</Tag>
                          <Tag>执行中 {summary.executing_pods_count}</Tag>
                        </Space>
                      </Space>
                    )}
                  </Card>
                </Col>
              ))}
            </Row>

            <Card title={`执行中 Pod (${data.executing_pods.length})`}>
              <PodTable data={data.executing_pods} />
            </Card>
          </>
        )}
      </Space>

      <Drawer
        title={selectedClusterSummary ? `${selectedClusterSummary.cluster_name} 节点资源使用情况` : '节点资源使用情况'}
        width={920}
        open={Boolean(selectedClusterSummary)}
        onClose={() => setSelectedClusterSummary(null)}
      >
        {selectedClusterSummary?.error ? (
          <Alert type="error" showIcon message="集群查询失败" description={selectedClusterSummary.error} />
        ) : (
          <NodeResourceTable data={selectedClusterSummary?.node_resources || []} />
        )}
      </Drawer>
    </div>
  )
}

export default ResourceDashboard
