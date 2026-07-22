import { useState } from 'react'
import { Alert, Card, Empty, Input, Select, Space, Table, Tag, Tooltip, Typography } from 'antd'
import { CheckCircleOutlined, MinusOutlined, SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'

import { useTestCaseFeatureMatrix } from '../hooks/useTestBoard'
import type { TestCaseFeatureColumn, TestCaseFeatureMatrixRow } from '../services/testBoard'

const { Text } = Typography

const DIRECTORY_COLORS: Record<string, string> = {
  nightly: 'blue',
  pull_request: 'purple',
  weekly: 'cyan',
}

function renderFeatureCell(value: string | undefined) {
  if (!value) {
    return <MinusOutlined style={{ color: '#d9d9d9' }} />
  }

  return (
    <Tooltip title={value}>
      <CheckCircleOutlined style={{ color: '#52c41a' }} />
    </Tooltip>
  )
}

export default function TestCaseFeatureMatrixTab() {
  const { data, isLoading } = useTestCaseFeatureMatrix()
  const [searchText, setSearchText] = useState('')
  const [directoryFilter, setDirectoryFilter] = useState<string[]>([])
  const [cardCountFilter, setCardCountFilter] = useState<string[]>([])
  const [remarkFilter, setRemarkFilter] = useState<string[]>([])
  const [featureFilter, setFeatureFilter] = useState<string[]>([])

  const featureColumns = data?.feature_columns || []
  const rows = data?.rows || []
  const stats = data?.statistics
  const normalizedSearch = searchText.trim().toLowerCase()

  const filteredRows = rows.filter((row) => {
    if (normalizedSearch) {
      const haystack = [row.directory, row.case_name, row.card_count, row.remark]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()

      if (!haystack.includes(normalizedSearch)) {
        return false
      }
    }

    if (directoryFilter.length > 0 && !directoryFilter.includes(row.directory)) {
      return false
    }

    if (cardCountFilter.length > 0 && !cardCountFilter.includes(row.card_count || '')) {
      return false
    }

    if (remarkFilter.length > 0 && !remarkFilter.includes(row.remark || '')) {
      return false
    }

    if (featureFilter.length > 0 && !featureFilter.every((key) => Boolean(row.features[key]))) {
      return false
    }

    return true
  })

  const columns: ColumnsType<TestCaseFeatureMatrixRow> = [
    {
      title: '目录',
      dataIndex: 'directory',
      key: 'directory',
      fixed: 'left',
      width: 120,
      render: (directory: string) => (
        <Tag color={DIRECTORY_COLORS[directory] || 'default'}>
          {directory}
        </Tag>
      ),
    },
    {
      title: '测试用例',
      dataIndex: 'case_name',
      key: 'case_name',
      fixed: 'left',
      width: 360,
      ellipsis: true,
      render: (caseName: string) => (
        <Text style={{ fontFamily: "'SFMono-Regular', Consolas, monospace", fontSize: 12 }}>
          {caseName}
        </Text>
      ),
    },
    {
      title: '几卡',
      dataIndex: 'card_count',
      key: 'card_count',
      width: 90,
      render: (cardCount: string | null) => cardCount ? <Tag>{cardCount}</Tag> : '-',
    },
    {
      title: '命中特性',
      dataIndex: 'marked_feature_count',
      key: 'marked_feature_count',
      width: 90,
      sorter: (a, b) => a.marked_feature_count - b.marked_feature_count,
    },
    {
      title: '备注',
      dataIndex: 'remark',
      key: 'remark',
      width: 150,
      render: (remark: string | null) => {
        if (!remark) {
          return <Text type="secondary">-</Text>
        }

        return (
          <Tag color={remark.includes('未直接命中') ? 'orange' : 'default'}>
            {remark}
          </Tag>
        )
      },
    },
    ...featureColumns.map((column: TestCaseFeatureColumn) => ({
      title: (
        <Tooltip title={`命中 ${column.count} 条用例`}>
          <span>{column.title}</span>
        </Tooltip>
      ),
      key: column.key,
      width: 74,
      align: 'center' as const,
      render: (_value: unknown, row: TestCaseFeatureMatrixRow) => renderFeatureCell(row.features[column.key]),
    })),
  ]

  return (
    <div>
      {data && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message={`已导入 ${data.source_file} · 更新时间 ${dayjs(data.updated_at).format('YYYY-MM-DD HH:mm')} · 共 ${stats?.total_cases || 0} 条测试用例`}
        />
      )}

      <Card style={{ marginBottom: 12 }}>
        <Space size="middle" wrap>
          <Input
            placeholder="搜索目录、用例或备注"
            prefix={<SearchOutlined />}
            style={{ width: 260 }}
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            allowClear
          />
          <Select
            mode="multiple"
            placeholder="目录"
            style={{ minWidth: 150 }}
            value={directoryFilter}
            onChange={setDirectoryFilter}
            options={Object.entries(stats?.by_directory || {}).map(([key, count]) => ({
              label: `${key} (${count})`,
              value: key,
            }))}
            allowClear
          />
          <Select
            mode="multiple"
            placeholder="几卡"
            style={{ minWidth: 120 }}
            value={cardCountFilter}
            onChange={setCardCountFilter}
            options={Object.entries(stats?.by_card_count || {}).map(([key, count]) => ({
              label: `${key} (${count})`,
              value: key,
            }))}
            allowClear
          />
          <Select
            mode="multiple"
            placeholder="备注"
            style={{ minWidth: 180 }}
            value={remarkFilter}
            onChange={setRemarkFilter}
            options={Object.entries(stats?.by_remark || {}).map(([key, count]) => ({
              label: `${key} (${count})`,
              value: key,
            }))}
            allowClear
          />
          <Select
            mode="multiple"
            placeholder="特性"
            style={{ minWidth: 220 }}
            value={featureFilter}
            onChange={setFeatureFilter}
            options={featureColumns.map((column) => ({
              label: `${column.title} (${column.count})`,
              value: column.key,
            }))}
            allowClear
          />
        </Space>
      </Card>

      {stats && (
        <Card style={{ marginBottom: 12 }}>
          <Space size="large" wrap>
            <Text>当前结果 <strong>{filteredRows.length}</strong></Text>
            <Text>总用例 <strong>{stats.total_cases}</strong></Text>
            <Text>特性列 <strong>{stats.total_features}</strong></Text>
            <Text>未直接命中 <strong>{stats.unmatched_cases}</strong></Text>
            {Object.entries(stats.by_directory).map(([key, count]) => (
              <Text key={key}>{key}: <strong>{count}</strong></Text>
            ))}
          </Space>
        </Card>
      )}

      <Card>
        <Table
          columns={columns}
          dataSource={filteredRows}
          loading={isLoading}
          rowKey="id"
          pagination={{ pageSize: 30, showSizeChanger: false }}
          scroll={{ x: 840 + featureColumns.length * 74 }}
          size="small"
          locale={{
            emptyText: <Empty description="暂无测试用例矩阵数据" />,
          }}
        />
      </Card>
    </div>
  )
}
