import { useState, useEffect } from 'react'
import { Card, Row, Col, Statistic, Typography, Select, Spin, Table, Tag } from 'antd'
import {
  UserOutlined,
  LoginOutlined,
  BarChartOutlined,
  RiseOutlined,
} from '@ant-design/icons'
import {
  getLoginStats,
  getFeatureUsageStats,
  LoginStatsResponse,
  FeatureUsageStatsResponse,
} from '../services/auth'

const { Title } = Typography

function UserStats() {
  const [loginDays, setLoginDays] = useState(30)
  const [usageDays, setUsageDays] = useState(30)
  const [loginStats, setLoginStats] = useState<LoginStatsResponse | null>(null)
  const [usageStats, setUsageStats] = useState<FeatureUsageStatsResponse | null>(null)
  const [loadingLogin, setLoadingLogin] = useState(false)
  const [loadingUsage, setLoadingUsage] = useState(false)

  const loadLoginStats = async (days: number) => {
    setLoadingLogin(true)
    try {
      const stats = await getLoginStats(days)
      setLoginStats(stats)
    } catch (e) {
      console.error('Failed to load login stats:', e)
    } finally {
      setLoadingLogin(false)
    }
  }

  const loadUsageStats = async (days: number) => {
    setLoadingUsage(true)
    try {
      const stats = await getFeatureUsageStats(days)
      setUsageStats(stats)
    } catch (e) {
      console.error('Failed to load usage stats:', e)
    } finally {
      setLoadingUsage(false)
    }
  }

  useEffect(() => {
    loadLoginStats(loginDays)
    loadUsageStats(usageDays)
  }, [loginDays, usageDays])

  const maxLoginTrendCount = loginStats?.login_trend
    ? Math.max(...loginStats.login_trend.map(t => t.count), 1)
    : 1

  const maxUsageTrendCount = usageStats?.daily_trend
    ? Math.max(...usageStats.daily_trend.map(t => t.count), 1)
    : 1

  return (
    <div className="stripe-ci-page">
      <div className="stripe-page-header">
        <Title level={3} className="stripe-page-title">
          <BarChartOutlined style={{ marginRight: 8 }} />
          用户统计
        </Title>
      </div>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card
            title="登录统计"
            extra={
              <Select
                value={loginDays}
                onChange={(v) => setLoginDays(v)}
                options={[
                  { label: '最近 7 天', value: 7 },
                  { label: '最近 30 天', value: 30 },
                  { label: '最近 90 天', value: 90 },
                ]}
                style={{ width: 120 }}
              />
            }
          >
            {loadingLogin ? (
              <Spin />
            ) : loginStats ? (
              <>
                <Row gutter={16}>
                  <Col span={6}>
                    <Statistic title="总用户数" value={loginStats.total_users} prefix={<UserOutlined />} />
                  </Col>
                  <Col span={6}>
                    <Statistic title="今日活跃" value={loginStats.active_users_today} prefix={<LoginOutlined />} />
                  </Col>
                  <Col span={6}>
                    <Statistic title="7日活跃" value={loginStats.active_users_7days} prefix={<RiseOutlined />} />
                  </Col>
                  <Col span={6}>
                    <Statistic title="30日活跃" value={loginStats.active_users_30days} prefix={<RiseOutlined />} />
                  </Col>
                </Row>

                <div style={{ marginTop: 24 }}>
                  <Title level={5}>登录趋势</Title>
                  <div style={{
                    display: 'flex',
                    alignItems: 'flex-end',
                    gap: 4,
                    height: 120,
                    padding: '8px 0',
                  }}>
                    {loginStats.login_trend.map((point) => (
                      <div key={point.date} style={{ flex: 1, textAlign: 'center' }}>
                        <div style={{
                          height: `${Math.max((point.count / maxLoginTrendCount) * 100, 2)}%`,
                          minHeight: 2,
                          background: 'var(--stripe-purple)',
                          borderRadius: 2,
                          transition: 'height 0.3s ease',
                        }} />
                        <div style={{ fontSize: 10, marginTop: 4, color: '#666' }}>
                          {point.date.slice(5)}
                        </div>
                        <div style={{ fontSize: 10, fontWeight: 600 }}>
                          {point.count}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div style={{ marginTop: 16 }}>
                  <Title level={5}>活跃用户排行</Title>
                  <Table
                    dataSource={loginStats.top_users_by_login_count}
                    rowKey="user_id"
                    size="small"
                    pagination={false}
                    columns={[
                      { title: '用户名', dataIndex: 'username', key: 'username' },
                      { title: '登录次数', dataIndex: 'login_count', key: 'login_count', sorter: (a, b) => a.login_count - b.login_count },
                    ]}
                  />
                </div>
              </>
            ) : null}
          </Card>
        </Col>

        <Col span={24}>
          <Card
            title="功能使用统计"
            extra={
              <Select
                value={usageDays}
                onChange={(v) => setUsageDays(v)}
                options={[
                  { label: '最近 7 天', value: 7 },
                  { label: '最近 30 天', value: 30 },
                  { label: '最近 90 天', value: 90 },
                ]}
                style={{ width: 120 }}
              />
            }
          >
            {loadingUsage ? (
              <Spin />
            ) : usageStats ? (
              <>
                <Statistic
                  title="总请求次数"
                  value={usageStats.total_requests}
                  prefix={<BarChartOutlined />}
                  style={{ marginBottom: 16 }}
                />

                <Row gutter={16}>
                  <Col span={12}>
                    <Title level={5}>功能使用排行</Title>
                    <Table
                      dataSource={usageStats.feature_ranking}
                      rowKey="feature_name"
                      size="small"
                      pagination={false}
                      columns={[
                        {
                          title: '功能',
                          dataIndex: 'feature_name',
                          key: 'feature_name',
                          render: (name: string) => <Tag color="purple">{name}</Tag>,
                        },
                        { title: '次数', dataIndex: 'count', key: 'count', sorter: (a, b) => a.count - b.count },
                      ]}
                    />
                  </Col>
                  <Col span={12}>
                    <Title level={5}>用户活跃排行</Title>
                    <Table
                      dataSource={usageStats.user_activity_ranking}
                      rowKey="user_id"
                      size="small"
                      pagination={false}
                      columns={[
                        { title: '用户名', dataIndex: 'username', key: 'username' },
                        { title: '操作次数', dataIndex: 'count', key: 'count', sorter: (a, b) => a.count - b.count },
                      ]}
                    />
                  </Col>
                </Row>

                <div style={{ marginTop: 16 }}>
                  <Title level={5}>请求趋势</Title>
                  <div style={{
                    display: 'flex',
                    alignItems: 'flex-end',
                    gap: 4,
                    height: 120,
                    padding: '8px 0',
                  }}>
                    {usageStats.daily_trend.map((point) => (
                      <div key={point.date} style={{ flex: 1, textAlign: 'center' }}>
                        <div style={{
                          height: `${Math.max((point.count / maxUsageTrendCount) * 100, 2)}%`,
                          minHeight: 2,
                          background: 'var(--stripe-purple)',
                          borderRadius: 2,
                          transition: 'height 0.3s ease',
                        }} />
                        <div style={{ fontSize: 10, marginTop: 4, color: '#666' }}>
                          {point.date.slice(5)}
                        </div>
                        <div style={{ fontSize: 10, fontWeight: 600 }}>
                          {point.count}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            ) : null}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default UserStats
