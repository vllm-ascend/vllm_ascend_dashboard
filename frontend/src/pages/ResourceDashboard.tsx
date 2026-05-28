import { useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Drawer,
  Empty,
  Input,
  Progress,
  Row,
  Select,
  Skeleton,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useQuery, useQueries } from '@tanstack/react-query'
import dayjs from 'dayjs'
import {
  ClusterResourceSummary,
  ResourceNodeInfo,
  ResourcePodInfo,
  ResourceQuantity,
  getEnabledResourceClusters,
  getClusterSummary,
} from '../services/resourceDashboard'

const { Title, Text } = Typography

const formatCpu = (value: number) => `${value.toFixed(2)} 核`
const formatMemory = (bytes: number) => `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GiB`
const formatNpu = (value: number) => `${value.toFixed(0)} 卡`

const percent = (used: number, total: number) => (total > 0 ? Math.round(Math.min((used / total) * 100, 100)) : 0)
const usageColor = (value: number) => (value >= 90 ? '#ff4d4f' : value >= 50 ? '#1677ff' : '#52c41a')

function ResourceUsage({ summary }: { summary: ClusterResourceSummary }) {
  const cpuPct = percent(summary.used.cpu_cores, summary.total.cpu_cores)
  const memPct = percent(summary.used.memory_bytes, summary.total.memory_bytes)
  const npuPct = percent(summary.used.npu, summary.total.npu)

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="small">
      <div>
        <Text>CPU {formatCpu(summary.used.cpu_cores)} / {formatCpu(summary.total.cpu_cores)}</Text>
        <Progress percent={cpuPct} strokeColor={usageColor(cpuPct)} status="normal" size="small" />
      </div>
      <div>
        <Text>内存 {formatMemory(summary.used.memory_bytes)} / {formatMemory(summary.total.memory_bytes)}</Text>
        <Progress percent={memPct} strokeColor={usageColor(memPct)} status="normal" size="small" />
      </div>
      <div>
        <Text>NPU {formatNpu(summary.used.npu)} / {formatNpu(summary.total.npu)}</Text>
        <Progress percent={npuPct} strokeColor={usageColor(npuPct)} status="normal" size="small" />
      </div>
    </Space>
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
      scroll={{ x: 1060 }}
      columns={[
        { title: '集群', dataIndex: 'cluster_name', width: 140 },
        { title: 'Namespace', dataIndex: 'namespace', width: 160 },
        { title: 'Pod', dataIndex: 'name', width: 260 },
        {
          title: 'PR ID',
          width: 100,
          render: (_, record) => record.pr_number && record.pr_url ? <a href={record.pr_url} target="_blank" rel="noreferrer">#{record.pr_number}</a> : '-',
          filterDropdown: ({ setSelectedKeys, selectedKeys, confirm, clearFilters }) => (
            <Space direction="vertical" style={{ padding: 8 }}>
              <Input
                placeholder="搜索 PR ID"
                value={selectedKeys[0] as string}
                onChange={event => setSelectedKeys(event.target.value ? [event.target.value] : [])}
                onPressEnter={() => confirm()}
                style={{ width: 160 }}
              />
              <Space>
                <Button type="primary" size="small" onClick={() => confirm()}>搜索</Button>
                <Button size="small" onClick={() => { clearFilters?.(); confirm() }}>重置</Button>
              </Space>
            </Space>
          ),
          onFilter: (value, record) => String(record.pr_number || '').includes(String(value)),
        },
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
            .sort((a, b) => a - b)
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

  const { data: allClusters = [], isLoading: clustersLoading } = useQuery({
    queryKey: ['resource-clusters-enabled'],
    queryFn: getEnabledResourceClusters,
  })

  const clusterOptions = allClusters.map(c => ({ label: c.name, value: c.id }))

  const activeClusterIds = appliedFilters.clusterIds.length
    ? allClusters.filter(c => appliedFilters.clusterIds.includes(c.id)).map(c => c.id)
    : allClusters.map(c => c.id)

  const clusterQueries = useQueries({
    queries: activeClusterIds.map(clusterId => ({
      queryKey: ['cluster-summary', clusterId],
      queryFn: () => getClusterSummary(clusterId),
      refetchInterval: 60000,
      placeholderData: (prev: ClusterResourceSummary | undefined) => prev,
      retry: false,
    })),
  })

  const arrivedSummaries = useMemo(
    () => clusterQueries.filter(q => q.data && !q.data.error).map(q => q.data!),
    [clusterQueries],
  )

  const failedSummaries = useMemo(
    () => clusterQueries.filter(q => q.data?.error).map(q => q.data!),
    [clusterQueries],
  )

  const overall = useMemo(() => ({
    total: {
      cpu_cores: arrivedSummaries.reduce((s, c) => s + c.total.cpu_cores, 0),
      memory_bytes: arrivedSummaries.reduce((s, c) => s + c.total.memory_bytes, 0),
      npu: arrivedSummaries.reduce((s, c) => s + c.total.npu, 0),
    },
    used: {
      cpu_cores: arrivedSummaries.reduce((s, c) => s + c.used.cpu_cores, 0),
      memory_bytes: arrivedSummaries.reduce((s, c) => s + c.used.memory_bytes, 0),
      npu: arrivedSummaries.reduce((s, c) => s + c.used.npu, 0),
    },
    available: {
      cpu_cores: arrivedSummaries.reduce((s, c) => s + c.available.cpu_cores, 0),
      memory_bytes: arrivedSummaries.reduce((s, c) => s + c.available.memory_bytes, 0),
      npu: arrivedSummaries.reduce((s, c) => s + c.available.npu, 0),
    },
    running_instances: arrivedSummaries.reduce((s, c) => s + c.running_instances, 0),
    executing_pods_count: arrivedSummaries.reduce((s, c) => s + c.executing_pods_count, 0),
    executed_pods_count: arrivedSummaries.reduce((s, c) => s + c.executed_pods_count, 0),
  }), [arrivedSummaries])

  const executingPods = useMemo(
    () => arrivedSummaries.flatMap(c => c.executing_pods || []),
    [arrivedSummaries],
  )

  const anyLoading = clustersLoading || (clusterQueries.some(q => q.isLoading) && arrivedSummaries.length === 0)
  const anyFetching = clusterQueries.some(q => q.isFetching)

  const applyFilters = () => setAppliedFilters({ clusterIds: selectedClusters })
  const resetFilters = () => { setSelectedClusters([]); setAppliedFilters({ clusterIds: [] }) }

  if (anyLoading) {
    return (
      <div style={{ padding: 24 }}>
        <Skeleton active paragraph={{ rows: 2 }} style={{ marginBottom: 24 }} />
        <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
          <Col xs={24} md={8}><Card><Skeleton active paragraph={{ rows: 1 }} /></Card></Col>
          <Col xs={24} md={8}><Card><Skeleton active paragraph={{ rows: 1 }} /></Card></Col>
        </Row>
        <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
          <Col xs={24} md={8}><Card><Skeleton active paragraph={{ rows: 1 }} /></Card></Col>
          <Col xs={24} md={8}><Card><Skeleton active paragraph={{ rows: 1 }} /></Card></Col>
          <Col xs={24} md={8}><Card><Skeleton active paragraph={{ rows: 1 }} /></Card></Col>
        </Row>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12} xl={8}><Card><Skeleton active paragraph={{ rows: 5 }} /></Card></Col>
          <Col xs={24} lg={12} xl={8}><Card><Skeleton active paragraph={{ rows: 5 }} /></Card></Col>
          <Col xs={24} lg={12} xl={8}><Card><Skeleton active paragraph={{ rows: 5 }} /></Card></Col>
        </Row>
      </div>
    )
  }

  return (
    <div className="stripe-page-container">
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <Title level={2}>资源看板</Title>
            <Text type="secondary">查看多个 Kubernetes 资源池的 CPU、内存和 NPU 分配情况</Text>
          </div>
          <Button icon={<ReloadOutlined />} onClick={() => clusterQueries.forEach(q => q.refetch())} loading={anyFetching}>{anyFetching ? '刷新中…' : '刷新'}</Button>
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

        {anyFetching && (
          <Alert type="info" showIcon message="正在刷新资源数据…" banner />
        )}

        {failedSummaries.length > 0 && (
          <Alert
            type="warning"
            showIcon
            message={`以下集群查询失败：${failedSummaries.map(c => c.cluster_name).join('、')}`}
            description={failedSummaries.map(c => c.error).filter(Boolean).join('；')}
          />
        )}

        <Row gutter={[16, 16]}>
          <Col xs={24} md={8}><Card><Statistic title="运行实例" value={overall.running_instances} /></Card></Col>
          <Col xs={24} md={8}><Card><Statistic title="执行中 Pod" value={overall.executing_pods_count} /></Card></Col>
          <Col xs={24} md={8}><Card><Statistic title="可用 NPU" value={formatNpu(overall.available.npu)} /></Card></Col>
        </Row>

        <Row gutter={[16, 16]}>
          <Col xs={24} md={8}><Card><Statistic title="CPU 总量" value={formatCpu(overall.total.cpu_cores)} /></Card></Col>
          <Col xs={24} md={8}><Card><Statistic title="内存总量" value={formatMemory(overall.total.memory_bytes)} /></Card></Col>
          <Col xs={24} md={8}><Card><Statistic title="NPU 总量" value={formatNpu(overall.total.npu)} /></Card></Col>
        </Row>

        <Row gutter={[16, 16]}>
          {clusterQueries.map((query, index) => {
            const cluster = allClusters.find(c => c.id === activeClusterIds[index])
            if (!cluster) return null
            return (
              <Col xs={24} lg={12} xl={8} key={cluster.id}>
                <Card
                  hoverable
                  title={cluster.name}
                  extra={
                    query.error ? <Tag color="red">异常</Tag>
                      : query.data?.error ? <Tag color="red">异常</Tag>
                        : query.isLoading ? <Tag color="blue">加载中</Tag>
                          : <Tag color="green">正常</Tag>
                  }
                  onClick={() => query.data && setSelectedClusterSummary(query.data)}
                  style={{ cursor: query.data ? 'pointer' : 'default' }}
                >
                  {query.error ? (
                    <Alert type="error" showIcon message="集群查询失败" description={(query.error as Error).message} />
                  ) : query.isLoading ? (
                    <Skeleton active paragraph={{ rows: 4 }} />
                  ) : query.data?.error ? (
                    <Alert type="error" showIcon message="集群查询失败" description={query.data.error} />
                  ) : query.data ? (
                    <Space direction="vertical" style={{ width: '100%' }}>
                      <ResourceUsage summary={query.data} />
                      <Space wrap>
                        <Tag>运行实例 {query.data.running_instances}</Tag>
                        <Tag>执行中 {query.data.executing_pods_count}</Tag>
                      </Space>
                    </Space>
                  ) : null}
                </Card>
              </Col>
            )
          })}
        </Row>

        <Card title={`执行中 Pod (${executingPods.length})`}>
          <PodTable data={executingPods} />
        </Card>
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