import { useState } from 'react'
import { Form, Input, Button, Card, message, Typography } from 'antd'
import { UserOutlined, LockOutlined, MailOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { register } from '../services/auth'
import './Login.css'
import vllmAscendLogo from '../assets/vllm-ascend-logo.png'

const { Title, Paragraph } = Typography

interface RegisterFormValues {
  username: string
  email: string
  password: string
}

function Register() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)

  const onFinish = async (values: RegisterFormValues) => {
    setLoading(true)
    try {
      await register(values)
      message.success('注册成功，请登录')
      navigate('/login')
    } catch (error: any) {
      message.error(error.response?.data?.detail || '注册失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="stripe-login-page">
      <div className="stripe-login-background">
        <div className="stripe-login-gradient-orb stripe-login-orb-1" />
        <div className="stripe-login-gradient-orb stripe-login-orb-2" />
      </div>

      <div className="stripe-login-container">
        <div className="stripe-login-header">
          <div className="stripe-login-logo">
            <img src={vllmAscendLogo} alt="vLLM Ascend" className="stripe-login-logo-img" />
          </div>
          <Title level={2} className="stripe-login-title">
            注册新账号
          </Title>
          <Paragraph className="stripe-login-subtitle">
            vLLM Ascend 社区看板
          </Paragraph>
        </div>

        <Card className="stripe-login-card">
          <Form
            name="register"
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
                { pattern: /^[a-zA-Z0-9_-]+$/, message: '仅支持字母、数字、下划线和连字符' },
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
              name="email"
              label="邮箱"
              className="stripe-form-item"
              rules={[
                { required: true, message: '请输入邮箱' },
                { type: 'email', message: '请输入有效的邮箱地址' },
              ]}
            >
              <Input
                prefix={<MailOutlined className="stripe-input-icon" />}
                placeholder="请输入邮箱"
                autoComplete="email"
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
                autoComplete="new-password"
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
                {loading ? '注册中...' : '注册'}
              </Button>
            </Form.Item>

            <div style={{ textAlign: 'center', marginTop: 16 }}>
              <Button
                type="link"
                onClick={() => navigate('/login')}
                style={{ color: 'var(--stripe-purple)' }}
              >
                已有账号？点击登录
              </Button>
            </div>
          </Form>
        </Card>
      </div>
    </div>
  )
}

export default Register
