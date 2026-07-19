import { useState } from 'react'
import {
  Card,
  Table,
  Tag,
  Select,
  Space,
  Typography,
  Button,
  Modal,
  Input,
  Form,
  message,
  Switch,
} from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  useNightlyTestCases,
  useCreateNightlyTestCase,
  useUpdateNightlyTestCase,
} from '../hooks/useCI'
import type { NightlyTestCase } from '../services/ci'

const { Text, Title } = Typography

const WORKFLOW_OPTIONS = [
  { label: 'Nightly-A2', value: 'Nightly-A2' },
  { label: 'Nightly-A3', value: 'Nightly-A3' },
]

function NightlyTestCaseConfig() {
  const [workflowFilter, setWorkflowFilter] = useState<string | undefined>(undefined)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingRecord, setEditingRecord] = useState<NightlyTestCase | null>(null)
  const [form] = Form.useForm()

  const { data: testCases, isLoading, refetch } = useNightlyTestCases({
    workflow_name: workflowFilter,
  })
  const createMutation = useCreateNightlyTestCase()
  const updateMutation = useUpdateNightlyTestCase()

  const handleAdd = () => {
    setEditingRecord(null)
    form.resetFields()
    form.setFieldsValue({ enabled: true })
    setModalOpen(true)
  }

  const handleEdit = (record: NightlyTestCase) => {
    setEditingRecord(record)
    form.setFieldsValue(record)
    setModalOpen(true)
  }

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      if (editingRecord) {
        await updateMutation.mutateAsync({ id: editingRecord.id, data: values })
        message.success('已更新')
      } else {
        await createMutation.mutateAsync(values)
        message.success('已创建')
      }
      setModalOpen(false)
    } catch (error: any) {
      if (error?.response?.data?.detail) {
        message.error(error.response.data.detail)
      }
    }
  }

  const columns = [
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 80,
      render: (enabled: boolean) => (
        enabled
          ? <Tag color="green">正常</Tag>
          : <Tag color="default">已过时</Tag>
      ),
    },
    {
      title: 'Workflow',
      dataIndex: 'workflow_name',
      key: 'workflow_name',
      width: 120,
      render: (text: string) => <Tag color="blue">{text}</Tag>,
    },
    {
      title: 'Job 名称',
      dataIndex: 'job_name',
      key: 'job_name',
      width: 240,
      ellipsis: true,
      render: (text: string) => <Text>{text}</Text>,
    },
    {
      title: '显示名',
      dataIndex: 'display_name',
      key: 'display_name',
      width: 140,
      ellipsis: true,
      render: (text: string | null) => text || '-',
    },
    {
      title: '测试模型',
      dataIndex: 'test_model',
      key: 'test_model',
      width: 160,
      ellipsis: true,
      render: (text: string | null) => text || '-',
    },
    {
      title: '模型 FO',
      dataIndex: 'model_fo',
      key: 'model_fo',
      width: 90,
      render: (text: string | null) => text || '-',
    },
    {
      title: '负责人',
      dataIndex: 'owner',
      key: 'owner',
      width: 90,
      render: (text: string | null) => text || '-',
    },
    {
      title: '部署方式',
      dataIndex: 'deployment_type',
      key: 'deployment_type',
      width: 120,
      ellipsis: true,
      render: (text: string | null) => text || '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 80,
      render: (_: any, record: NightlyTestCase) => (
        <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
          编辑
        </Button>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>Nightly 用例配置</Title>
          <Text type="secondary">管理 Nightly 流水线中的静态用例，过时用例标记而非删除</Text>
        </div>
        <Space>
          <Select
            value={workflowFilter}
            onChange={setWorkflowFilter}
            allowClear
            placeholder="筛选 Workflow"
            options={WORKFLOW_OPTIONS}
            style={{ width: 150 }}
          />
          <Button icon={<ReloadOutlined />} onClick={() => refetch()}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>新增用例</Button>
        </Space>
      </div>

      <Card>
        <Table
          columns={columns}
          dataSource={testCases}
          loading={isLoading}
          rowKey="id"
          pagination={{ pageSize: 20, showSizeChanger: false }}
          scroll={{ x: 1200 }}
          size="middle"
        />
      </Card>

      <Modal
        title={editingRecord ? '编辑用例' : '新增用例'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
        okText="保存"
        cancelText="取消"
        width={560}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="workflow_name" label="Workflow" rules={[{ required: true, message: '请选择' }]}>
            <Select options={WORKFLOW_OPTIONS} placeholder="选择 Workflow" />
          </Form.Item>
          <Form.Item name="job_name" label="Job 名称" rules={[{ required: true, message: '请输入 job 名称' }]}>
            <Input placeholder="如 single-node (main, xxx, ...)" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名">
            <Input placeholder="可选的显示名称" />
          </Form.Item>
          <Space size={16} style={{ width: '100%' }}>
            <Form.Item name="test_model" label="测试模型" style={{ width: 240 }}>
              <Input placeholder="如 MiniMax-M3-BF16" />
            </Form.Item>
            <Form.Item name="model_fo" label="模型 FO" style={{ width: 240 }}>
              <Input placeholder="模型负责人" />
            </Form.Item>
          </Space>
          <Space size={16} style={{ width: '100%' }}>
            <Form.Item name="owner" label="测试负责人" style={{ width: 240 }}>
              <Input placeholder="测试负责人" />
            </Form.Item>
            <Form.Item name="deployment_type" label="部署方式" style={{ width: 240 }}>
              <Input placeholder="如 single-node / pd-disagg" />
            </Form.Item>
          </Space>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="备注信息" />
          </Form.Item>
          <Form.Item name="enabled" label="已过时" valuePropName="checked">
            <Switch checkedChildren="否" unCheckedChildren="是" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default NightlyTestCaseConfig
