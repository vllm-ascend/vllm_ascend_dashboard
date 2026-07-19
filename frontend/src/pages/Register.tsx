import { useState } from 'react'
import { Form, Input, Button, Card, message } from 'antd'
import { ArrowLeftOutlined, ArrowRightOutlined, LockOutlined, MailOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import { register } from '../services/auth'
import './Login.css'
import BrandMark from '../components/BrandMark'

function Register() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)

  const onFinish = async (values: { username: string; email: string; password: string }) => {
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
    <main className="login-page auth-register-page">
      <section className="login-story" aria-label="注册说明">
        <div className="login-story-inner">
          <Link className="login-brand" to="/" aria-label="返回 vLLM Ascend 首页">
            <BrandMark title="vLLM Ascend" />
            <div><span>Community Operations</span></div>
          </Link>
          <div className="login-story-copy">
            <span className="login-kicker">JOIN THE COMMUNITY</span>
            <h1>与社区一起，<br />让每次交付更清晰。</h1>
            <p>创建账号后，你可以查看工程健康状态、参与问题诊断，并与维护者共享统一的社区运行视图。</p>
          </div>
          <div className="auth-progress" aria-label="注册流程">
            <span className="is-active"><i>1</i>创建账号</span><b /><span><i>2</i>登录工作台</span><b /><span><i>3</i>开始协作</span>
          </div>
        </div>
      </section>
      <section className="login-access" aria-label="账号注册">
        <Card className="login-card" variant="borderless">
          <Link className="auth-back-link" to="/"><ArrowLeftOutlined /> 返回首页</Link>
          <div className="login-card-header"><div className="login-security-icon"><SafetyCertificateOutlined /></div><span>社区账号</span></div>
          <h2>创建新账号</h2>
          <p className="login-card-subtitle">填写基本信息，加入 vLLM Ascend 社区工作台</p>
          <Form name="register" onFinish={onFinish} autoComplete="off" size="large" layout="vertical" requiredMark={false}>
            <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }, { min: 3, message: '用户名至少 3 个字符' }, { pattern: /^[a-zA-Z0-9_-]+$/, message: '仅支持字母、数字、下划线和连字符' }]}>
              <Input prefix={<UserOutlined />} placeholder="请输入用户名" autoComplete="username" />
            </Form.Item>
            <Form.Item name="email" label="邮箱" rules={[{ required: true, message: '请输入邮箱' }, { type: 'email', message: '请输入有效的邮箱地址' }]}>
              <Input prefix={<MailOutlined />} placeholder="name@example.com" autoComplete="email" />
            </Form.Item>
            <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }, { min: 6, message: '密码至少 6 个字符' }]}>
              <Input.Password prefix={<LockOutlined />} placeholder="至少 6 个字符" autoComplete="new-password" />
            </Form.Item>
            <Form.Item className="login-submit-item">
              <Button type="primary" htmlType="submit" loading={loading} block className="login-submit-button">
                {loading ? '正在创建…' : '创建账号'}{!loading && <ArrowRightOutlined />}
              </Button>
            </Form.Item>
          </Form>
          <div className="login-register-row"><span>已有账号？</span><Button type="link" onClick={() => navigate('/login')}>直接登录</Button></div>
          <p className="login-help-text">创建账号即表示你同意遵守社区协作规范。</p>
        </Card>
      </section>
    </main>
  )
}

export default Register
