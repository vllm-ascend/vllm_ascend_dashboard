import { useState } from 'react'
import { Button, Card, Form, Input, message } from 'antd'
import {
  ArrowRightOutlined,
  CheckCircleFilled,
  LockOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { login } from '../services/auth'
import vllmAscendLogo from '../assets/vllm-ascend-logo.png'
import './Login.css'

interface LoginFormValues {
  username: string
  password: string
}

function Login() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [loading, setLoading] = useState(false)

  const onFinish = async (values: LoginFormValues) => {
    setLoading(true)
    try {
      const response = await login(values)
      localStorage.setItem('access_token', response.access_token)
      localStorage.setItem('refresh_token', response.refresh_token)
      queryClient.invalidateQueries({ queryKey: ['current-user'] })

      try {
        const { getCurrentUser } = await import('../services/auth')
        const userInfo = await getCurrentUser()
        localStorage.setItem('user_info', JSON.stringify(userInfo))
      } catch (error) {
        console.error('Failed to fetch user info:', error)
      }

      message.success('欢迎回来')
      navigate('/')
    } catch (error: any) {
      message.error(error.response?.data?.detail || '登录失败，请检查用户名和密码')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="login-page">
      <section className="login-story" aria-label="产品介绍">
        <div className="login-story-inner">
          <div className="login-brand">
            <img src={vllmAscendLogo} alt="vLLM Ascend" />
            <div>
              <strong>vLLM Ascend</strong>
              <span>Community Operations</span>
            </div>
          </div>

          <div className="login-story-copy">
            <span className="login-kicker">COMMUNITY INTELLIGENCE</span>
            <h1>把社区运行状态，<br />变成清晰的下一步行动。</h1>
            <p>统一掌握 CI、PR、模型验证、测试质量与算力资源，让维护者更快发现风险、更稳推进交付。</p>
          </div>

          <div className="login-value-list">
            <div><CheckCircleFilled /><span><strong>交付健康</strong>实时聚合 CI 与 PR 风险</span></div>
            <div><CheckCircleFilled /><span><strong>模型质量</strong>跟踪精度、性能与回归</span></div>
            <div><CheckCircleFilled /><span><strong>智能诊断</strong>从告警直接进入根因分析</span></div>
          </div>

          <div className="login-system-status">
            <span className="login-status-dot" />
            社区基础设施运行中
          </div>
        </div>
      </section>

      <section className="login-access" aria-label="账号登录">
        <Card className="login-card" bordered={false}>
          <div className="login-card-header">
            <div className="login-security-icon"><SafetyCertificateOutlined /></div>
            <span>安全访问</span>
          </div>
          <h2>登录工作台</h2>
          <p className="login-card-subtitle">使用你的社区看板账号继续</p>

          <Form
            name="login"
            onFinish={onFinish}
            autoComplete="off"
            size="large"
            layout="vertical"
            requiredMark={false}
          >
            <Form.Item
              name="username"
              label="用户名"
              rules={[
                { required: true, message: '请输入用户名' },
                { min: 3, message: '用户名至少 3 个字符' },
              ]}
            >
              <Input prefix={<UserOutlined />} placeholder="请输入用户名" autoComplete="username" />
            </Form.Item>

            <Form.Item
              name="password"
              label="密码"
              rules={[
                { required: true, message: '请输入密码' },
                { min: 6, message: '密码至少 6 个字符' },
              ]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder="请输入密码" autoComplete="current-password" />
            </Form.Item>

            <Form.Item className="login-submit-item">
              <Button type="primary" htmlType="submit" loading={loading} block className="login-submit-button">
                {loading ? '正在验证…' : '进入工作台'}
                {!loading && <ArrowRightOutlined />}
              </Button>
            </Form.Item>
          </Form>

          <div className="login-register-row">
            <span>还没有账号？</span>
            <Button type="link" onClick={() => navigate('/register')}>申请社区账号</Button>
          </div>

          <p className="login-help-text">访问遇到问题，请联系社区管理员。</p>
        </Card>
      </section>
    </main>
  )
}

export default Login
