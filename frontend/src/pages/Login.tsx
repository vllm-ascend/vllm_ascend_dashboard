import { useState } from 'react'
import { Form, Input, Button, Card, message, Typography } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { login } from '../services/auth'
import './Login.css'
import vllmAscendLogo from '../assets/vllm-ascend-logo.png'

const { Title, Paragraph } = Typography

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

      // 保存 Token
      localStorage.setItem('access_token', response.access_token)
      localStorage.setItem('refresh_token', response.refresh_token)

      // 清除用户信息缓存，确保重新获取最新角色
      queryClient.invalidateQueries({ queryKey: ['current-user'] })

      // 获取用户信息并保存（用于路由权限判断）
      try {
        const { getCurrentUser } = await import('../services/auth')
        const userInfo = await getCurrentUser()
        localStorage.setItem('user_info', JSON.stringify(userInfo))
      } catch (e) {
        console.error('Failed to fetch user info:', e)
      }

      message.success('登录成功')

      // 跳转到首页
      navigate('/')
    } catch (error: any) {
      message.error((error as any).response?.data?.detail || '登录失败，请检查用户名和密码')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="stripe-login-page">
      {/* Decorative Background Elements */}
      <div className="stripe-login-background">
        <div className="stripe-login-gradient-orb stripe-login-orb-1" />
        <div className="stripe-login-gradient-orb stripe-login-orb-2" />
      </div>
      
      <div className="stripe-login-container">
        {/* Logo Section */}
        <div className="stripe-login-header">
          <div className="stripe-login-logo">
            <img src={vllmAscendLogo} alt="vLLM Ascend" className="stripe-login-logo-img" />
          </div>
          <Title level={2} className="stripe-login-title">
            vLLM Ascend Dashboard
          </Title>
          <Paragraph className="stripe-login-subtitle">
            社区看板管理系统
          </Paragraph>
        </div>

        {/* Login Card */}
        <Card className="stripe-login-card">
          <Form
            name="login"
            onFinish={onFinish}
            autoComplete="off"
            size="large"
            layout="vertical"
          >
            <Form.Item
              name="username"
              label="用户名"
              className="stripe-form-item"
              rules={[
                { required: true, message: '请输入用户名' },
                { min: 3, message: '用户名至少 3 个字符' },
              ]}
            >
              <Input
                prefix={<UserOutlined className="stripe-input-icon" />}
                placeholder="请输入用户名"
                autoComplete="username"
                className="stripe-input"
              />
            </Form.Item>

            <Form.Item
              name="password"
              label="密码"
              className="stripe-form-item"
              rules={[
                { required: true, message: '请输入密码' },
                { min: 6, message: '密码至少 6 个字符' },
              ]}
            >
              <Input.Password
                prefix={<LockOutlined className="stripe-input-icon" />}
                placeholder="请输入密码"
                autoComplete="current-password"
                className="stripe-input"
              />
            </Form.Item>

            <Form.Item className="stripe-form-item-submit" style={{ marginBottom: 0 }}>
              <Button
                type="primary"
                htmlType="submit"
                loading={loading}
                block
                size="large"
                className="stripe-btn-primary stripe-login-btn"
              >
                {loading ? '登录中...' : '登录'}
              </Button>
            </Form.Item>

            <div style={{ textAlign: 'center', marginTop: 16 }}>
              <Button
                type="link"
                onClick={() => navigate('/register')}
                style={{ color: 'var(--stripe-purple)' }}
              >
                还没有账号？点击注册
              </Button>
            </div>
          </Form>
        </Card>
      </div>
    </div>
  )
}

export default Login
