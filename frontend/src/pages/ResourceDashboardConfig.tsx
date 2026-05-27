import { useState } from 'react'
import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { DeleteOutlined, EditOutlined, ExperimentOutlined, PlusOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnsType } from 'antd/es/table'
import {
  KubernetesCluster,
  KubernetesClusterCreate,
  KubernetesClusterUpdate,
  createResourceCluster,
  deleteResourceCluster,
  listResourceClusters,
  testResourceCluster,
  updateResourceCluster,
} from '../services/resourceDashboard'

const { TextArea } = Input
const { Title, Text } = Typography

function ResourceDashboardConfig() {
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const [modalOpen, setModalOpen] = useState(false)
  const [editingCluster, setEditingCluster] = useState<KubernetesCluster | null>(null)

  const { data = [], isLoading } = useQuery({
    queryKey: ['resource-clusters-admin'],
    queryFn: listResourceClusters,
  })

  const createMutation = useMutation({
    mutationFn: createResourceCluster,
    onSuccess: () => {
      message.success('集群配置已创建')
      queryClient.invalidateQueries({ queryKey: ['resource-clusters-admin'] })
      queryClient.invalidateQueries({ queryKey: ['resource-clusters-enabled'] })
      setModalOpen(false)
      form.resetFields()
    },
    onError: () => message.error('创建失败'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: KubernetesClusterUpdate }) => updateResourceCluster(id, data),
    onSuccess: () => {
      message.success('集群配置已更新')
      queryClient.invalidateQueries({ queryKey: ['resource-clusters-admin'] })
      queryClient.invalidateQueries({ queryKey: ['resource-clusters-enabled'] })
      queryClient.invalidateQueries({ queryKey: ['resource-dashboard'] })
      setModalOpen(false)
      setEditingCluster(null)
      form.resetFields()
    },
    onError: () => message.error('更新失败'),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteResourceCluster,
    onSuccess: () => {
      message.success('集群配置已删除')
      queryClient.invalidateQueries({ queryKey: ['resource-clusters-admin'] })
      queryClient.invalidateQueries({ queryKey: ['resource-clusters-enabled'] })
      queryClient.invalidateQueries({ queryKey: ['resource-dashboard'] })
    },
    onError: () => message.error('删除失败'),
  })

  const testMutation = useMutation({
    mutationFn: testResourceCluster,
    onSuccess: (result) => {
      if (result.success) {
        message.success(`${result.message}，节点 ${result.node_count} 个，Pod ${result.pod_count} 个`)
      } else {
        message.error(result.message)
      }
    },
    onError: () => message.error('连接测试失败'),
  })

  const openCreateModal = () => {
    setEditingCluster(null)
    form.resetFields()
    form.setFieldsValue({
      npu_resource_name: 'huawei.com/Ascend910',
      enabled: true,
      display_order: 0,
    })
    setModalOpen(true)
  }

  const openEditModal = (cluster: KubernetesCluster) => {
    setEditingCluster(cluster)
    form.setFieldsValue({
      name: cluster.name,
      description: cluster.description,
      context: cluster.context,
      default_label_selector: cluster.default_label_selector,
      npu_resource_name: cluster.npu_resource_name,
      enabled: cluster.enabled,
      display_order: cluster.display_order,
      kubeconfig: undefined,
    })
    setModalOpen(true)
  }

  const submitForm = async () => {
    const values = await form.validateFields()
    const payload = { ...values }

    if (editingCluster) {
      if (!payload.kubeconfig) {
        delete payload.kubeconfig
      }
      updateMutation.mutate({ id: editingCluster.id, data: payload })
    } else {
      createMutation.mutate(payload as KubernetesClusterCreate)
    }
  }

  const columns: ColumnsType<KubernetesCluster> = [
    { title: '名称', dataIndex: 'name', width: 160 },
    { title: '描述', dataIndex: 'description', render: value => value || '-' },
    {
      title: '状态',
      dataIndex: 'enabled',
      width: 90,
      render: enabled => <Tag color={enabled ? 'green' : 'default'}>{enabled ? '启用' : '停用'}</Tag>,
    },
    { title: 'Label Selector', dataIndex: 'default_label_selector', render: value => value || '-' },
    { title: 'NPU 资源名', dataIndex: 'npu_resource_name', width: 180 },
    { title: '排序', dataIndex: 'display_order', width: 80 },
    {
      title: 'Kubeconfig',
      dataIndex: 'kubeconfig_configured',
      width: 120,
      render: configured => <Tag color={configured ? 'green' : 'red'}>{configured ? '已配置' : '未配置'}</Tag>,
    },
    {
      title: '操作',
      width: 260,
      render: (_, record) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEditModal(record)}>编辑</Button>
          <Button size="small" icon={<ExperimentOutlined />} loading={testMutation.isPending} onClick={() => testMutation.mutate(record.id)}>测试</Button>
          <Popconfirm title="确认删除该集群配置？" onConfirm={() => deleteMutation.mutate(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div>
            <Title level={4}>资源看板配置</Title>
            <Text type="secondary">配置 Kubernetes 集群、Label 过滤和 NPU 资源名；Pod 固定读取 vllm-project namespace</Text>
          </div>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>新增集群</Button>
        </div>

        <Table<KubernetesCluster>
          rowKey="id"
          loading={isLoading}
          dataSource={data}
          columns={columns}
          scroll={{ x: 1200 }}
        />
      </Card>

      <Modal
        title={editingCluster ? '编辑 Kubernetes 集群' : '新增 Kubernetes 集群'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={submitForm}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
        width={760}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="集群名称" rules={[{ required: true, message: '请输入集群名称' }]}>
            <Input placeholder="例如：A2 资源池" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input placeholder="集群用途或备注" />
          </Form.Item>
          <Form.Item
            name="kubeconfig"
            label="Kubeconfig"
            rules={editingCluster ? [] : [{ required: true, message: '请输入 kubeconfig' }]}
            extra={editingCluster ? '编辑时留空表示不更新 kubeconfig' : undefined}
          >
            <TextArea rows={8} placeholder="粘贴 kubeconfig YAML 内容" />
          </Form.Item>
          <Form.Item name="context" label="Context">
            <Input placeholder="留空使用 kubeconfig 当前 context" />
          </Form.Item>
          <Form.Item name="default_label_selector" label="默认 Label Selector">
            <Input placeholder="app=vllm,team=infra" />
          </Form.Item>
          <Form.Item name="npu_resource_name" label="NPU 资源名" rules={[{ required: true, message: '请输入 NPU 资源名' }]}>
            <Input placeholder="huawei.com/Ascend910" />
          </Form.Item>
          <Form.Item name="display_order" label="排序">
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default ResourceDashboardConfig
