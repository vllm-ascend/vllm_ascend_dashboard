import React, { useMemo } from 'react'
import { Alert, Card, Col, Empty, Row, Space, Spin, Statistic, Tag, Tooltip, Typography } from 'antd'
import { BranchesOutlined } from '@ant-design/icons'
import { useFailureAnalysisKnowledgeGraph } from '../hooks/useFailureAnalysis'
import type {
  FailureAnalysisKnowledgeGraphEdge,
  FailureAnalysisKnowledgeGraphNode,
} from '../services/failureAnalysis'

const { Text, Paragraph } = Typography

const TYPE_LABELS: Record<string, string> = {
  analysis: '分析',
  job: 'Job',
  workflow: 'Workflow',
  failure_fact: '失败事实',
  hypothesis: '假设',
  evidence: '证据',
  code_ref: '代码',
  test: '测试',
  commit: '提交边界',
  candidate_review: '候选审查',
  validation: '验证',
  tool: '工具',
}

const TYPE_COLORS: Record<string, string> = {
  analysis: 'blue',
  job: 'red',
  workflow: 'geekblue',
  failure_fact: 'volcano',
  hypothesis: 'purple',
  evidence: 'green',
  code_ref: 'cyan',
  test: 'gold',
  commit: 'orange',
  candidate_review: 'magenta',
  validation: 'lime',
  tool: 'default',
}

const GROUPS: Array<{ title: string; types: string[] }> = [
  { title: '上下文', types: ['analysis', 'job', 'workflow', 'commit'] },
  { title: '失败与假设', types: ['failure_fact', 'hypothesis'] },
  { title: '证据与代码', types: ['evidence', 'code_ref', 'test'] },
  { title: '审查与验证', types: ['candidate_review', 'validation', 'tool'] },
]

interface Props {
  analysisId: number | null
}

export const FailureAnalysisKnowledgeGraph: React.FC<Props> = ({ analysisId }) => {
  const { data, isLoading, error } = useFailureAnalysisKnowledgeGraph(analysisId)

  const nodeById = useMemo(() => {
    const map = new Map<string, FailureAnalysisKnowledgeGraphNode>()
    data?.nodes.forEach(node => map.set(node.id, node))
    return map
  }, [data?.nodes])

  const edgesBySource = useMemo(() => groupEdges(data?.edges || [], 'source'), [data?.edges])
  const edgesByTarget = useMemo(() => groupEdges(data?.edges || [], 'target'), [data?.edges])

  if (!analysisId) {
    return <Empty description="暂无分析记录，无法生成知识图谱" />
  }

  if (isLoading) {
    return <Spin tip="加载知识图谱..." />
  }

  if (error) {
    return <Alert message="知识图谱加载失败" description={(error as Error).message} type="error" showIcon />
  }

  if (!data || data.nodes.length === 0) {
    return <Empty description="当前分析没有可展示的图谱数据" />
  }

  return (
    <div>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space size="large" wrap>
          <BranchesOutlined />
          <Statistic title="节点" value={data.stats.nodes || data.nodes.length} />
          <Statistic title="关系" value={data.stats.edges || data.edges.length} />
          <Statistic title="假设" value={data.stats.hypotheses || 0} />
          <Statistic title="证据" value={data.stats.evidence || 0} />
          <Statistic title="代码引用" value={data.stats.code_refs || 0} />
        </Space>
      </Card>

      <Row gutter={[12, 12]}>
        {GROUPS.map(group => {
          const groupNodes = data.nodes.filter(node => group.types.includes(node.type))
          return (
            <Col key={group.title} xs={24} lg={6}>
              <Card
                size="small"
                title={group.title}
                bodyStyle={{ padding: 10, maxHeight: 620, overflowY: 'auto' }}
              >
                {groupNodes.length === 0 ? (
                  <Text type="secondary">暂无</Text>
                ) : (
                  <Space direction="vertical" style={{ width: '100%' }} size={8}>
                    {groupNodes.map(node => (
                      <GraphNodeCard
                        key={node.id}
                        node={node}
                        outgoing={edgesBySource.get(node.id) || []}
                        incoming={edgesByTarget.get(node.id) || []}
                        nodeById={nodeById}
                      />
                    ))}
                  </Space>
                )}
              </Card>
            </Col>
          )
        })}
      </Row>
    </div>
  )
}

const GraphNodeCard: React.FC<{
  node: FailureAnalysisKnowledgeGraphNode
  outgoing: FailureAnalysisKnowledgeGraphEdge[]
  incoming: FailureAnalysisKnowledgeGraphEdge[]
  nodeById: Map<string, FailureAnalysisKnowledgeGraphNode>
}> = ({ node, outgoing, incoming, nodeById }) => {
  return (
    <Card size="small" style={{ borderColor: '#e5e7eb' }} bodyStyle={{ padding: 10 }}>
      <Space direction="vertical" size={4} style={{ width: '100%' }}>
        <Space size={4} wrap>
          <Tag color={TYPE_COLORS[node.type] || 'default'}>{TYPE_LABELS[node.type] || node.type}</Tag>
          {node.status && <Tag>{node.status}</Tag>}
          {node.confidence && <Tag color="blue">{node.confidence}</Tag>}
        </Space>
        <Tooltip title={node.title || node.label}>
          <Text strong style={{ width: '100%' }}>{node.label}</Text>
        </Tooltip>
        {node.title && (
          <Paragraph style={{ marginBottom: 0 }} ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}>
            {node.title}
          </Paragraph>
        )}
        {node.subtitle && <Text type="secondary">{node.subtitle}</Text>}
        {(outgoing.length > 0 || incoming.length > 0) && (
          <Space size={[4, 4]} wrap>
            {outgoing.slice(0, 6).map(edge => (
              <RelationTag key={edge.id} edge={edge} target={nodeById.get(edge.target)} direction="out" />
            ))}
            {incoming.slice(0, 4).map(edge => (
              <RelationTag key={edge.id} edge={edge} target={nodeById.get(edge.source)} direction="in" />
            ))}
          </Space>
        )}
      </Space>
    </Card>
  )
}

const RelationTag: React.FC<{
  edge: FailureAnalysisKnowledgeGraphEdge
  target?: FailureAnalysisKnowledgeGraphNode
  direction: 'in' | 'out'
}> = ({ edge, target, direction }) => {
  const label = `${direction === 'out' ? '→' : '←'} ${edge.label}: ${target?.label || '未知'}`
  return (
    <Tooltip title={label}>
      <Tag style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis' }}>{label}</Tag>
    </Tooltip>
  )
}

const groupEdges = (
  edges: FailureAnalysisKnowledgeGraphEdge[],
  key: 'source' | 'target',
) => {
  const map = new Map<string, FailureAnalysisKnowledgeGraphEdge[]>()
  edges.forEach(edge => {
    const value = edge[key]
    const list = map.get(value) || []
    list.push(edge)
    map.set(value, list)
  })
  return map
}
