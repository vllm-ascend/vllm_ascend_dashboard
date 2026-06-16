import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout as AntLayout, Menu, Button, Avatar, Dropdown, Space, Tag, Drawer } from 'antd'
import {
  BellOutlined,
  DashboardOutlined,
  CheckCircleOutlined,
  ExperimentOutlined,
  SettingOutlined,
  LogoutOutlined,
  UserOutlined,
  LoginOutlined,
  LockOutlined,
  GithubOutlined,
  MenuOutlined,
  CloudServerOutlined,
  MailOutlined,
  SendOutlined,
} from '@ant-design/icons'
import type { MenuProps } from 'antd'
import { logout } from '../services/auth'
import { message } from 'antd'
import { useCurrentUser } from '../hooks/useCurrentUser'
import vllmAscendLogo from '../assets/vllm-ascend-logo.png'
import ChangePasswordModal from './ChangePasswordModal'
import './Layout.css'

const { Header, Sider, Content } = AntLayout

const menuItems: MenuProps['items'] = [
  {
    key: '/',
    icon: <DashboardOutlined />,
    label: '首页',
  },
  {
    key: '/project',
    icon: <GithubOutlined />,
    label: '项目看板',
  },
  {
    key: '/ci',
    icon: <CheckCircleOutlined />,
    label: 'CI 看板',
  },
  {
    key: '/models',
    icon: <ExperimentOutlined />,
    label: '模型看板',
  },
  {
    key: '/resources',
    icon: <CloudServerOutlined />,
    label: '资源看板',
  },
  {
    key: '/alert-rules',
    icon: <BellOutlined />,
    label: '告警规则',
  },
]

// 仅管理员可见的菜单项
const adminMenuItems: MenuProps['items'] = [
  {
    key: '/admin',
    icon: <SettingOutlined />,
    label: '系统管理',
  },
  {
    key: '/admin/smtp-config',
    icon: <MailOutlined />,
    label: '邮件服务器',
  },
  {
    key: '/admin/daily-report',
    icon: <SendOutlined />,
    label: '每日报告',
  },
]

function Layout() {
  const [changePasswordModalOpen, setChangePasswordModalOpen] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const { data: currentUser } = useCurrentUser()
  const hasAdminRole = currentUser?.role === 'admin' || currentUser?.role === 'super_admin'
  const isLoggedIn = !!localStorage.getItem('access_token')

  // 合并菜单项（根据权限）
  const allMenuItems: MenuProps['items'] = hasAdminRole
    ? [...(menuItems || []), ...(adminMenuItems || [])]
    : menuItems || []

  const handleLogout = async () => {
    try {
      await logout()
    } catch (error) {
      console.error('Logout error:', error)
    } finally {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('user_info')
      message.success('已成功登出')
      navigate('/login')
    }
  }

  const userMenuItems: MenuProps['items'] = [
    {
      key: 'change-password',
      icon: <LockOutlined />,
      label: '修改密码',
      onClick: () => setChangePasswordModalOpen(true),
    },
    {
      type: 'divider',
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      onClick: handleLogout,
    },
  ]

  // 获取用户头像首字母
  const getUserInitial = () => {
    if (currentUser?.username) {
      return currentUser.username.charAt(0).toUpperCase()
    }
    return 'U'
  }

  // 获取角色标签
  const getRoleTag = () => {
    if (!currentUser?.role) return null

    const roleConfig: Record<string, { color: string; label: string }> = {
      super_admin: { color: 'red', label: '超级管理员' },
      admin: { color: 'orange', label: '管理员' },
      user: { color: 'blue', label: '用户' },
    }

    const config = roleConfig[currentUser.role] || { color: 'default', label: currentUser.role }
    return <Tag color={config.color}>{config.label}</Tag>
  }

  // 移动端菜单项
  const mobileMenuItems = [
    { key: '/', icon: <DashboardOutlined />, label: '首页' },
    { key: '/project', icon: <GithubOutlined />, label: '项目看板' },
    { key: '/ci', icon: <CheckCircleOutlined />, label: 'CI 看板' },
    { key: '/models', icon: <ExperimentOutlined />, label: '模型看板' },
    { key: '/resources', icon: <CloudServerOutlined />, label: '资源看板' },
    ...(hasAdminRole ? [
      { key: '/admin', icon: <SettingOutlined />, label: '系统管理' },
      { key: '/admin/daily-report', icon: <MailOutlined />, label: '每日报告' },
    ] : []),
  ]

  return (
    <AntLayout className="stripe-layout">
      {/* Desktop Sider */}
      <Sider 
        className="stripe-sider"
        width={240}
        theme="dark"
      >
        <div className="stripe-logo-container">
          <img
            src={vllmAscendLogo}
            alt="vLLM Ascend"
            className="stripe-logo"
          />
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={allMenuItems}
          onClick={({ key }) => navigate(key)}
          className="stripe-menu"
        />
      </Sider>
      
      <AntLayout>
        {/* Stripe-style Header */}
        <Header className="stripe-header">
          <div className="stripe-header-content">
            {/* Mobile menu toggle */}
            <Button
              type="text"
              icon={<MenuOutlined />}
              onClick={() => setMobileMenuOpen(true)}
              className="mobile-menu-toggle"
              style={{
                fontSize: 18,
                color: 'var(--deep-navy)',
              }}
            />
            
            {/* Logo for mobile */}
            <div className="stripe-header-logo">
              <img src={vllmAscendLogo} alt="vLLM Ascend" />
            </div>

            <div style={{ flex: 1 }} />

            <Space className="stripe-header-actions" size="middle">
              {isLoggedIn ? (
                <Dropdown
                  menu={{ items: userMenuItems }}
                  placement="bottomRight"
                  arrow
                  className="stripe-user-dropdown"
                >
                  <Space className="stripe-user-info" style={{ marginLeft: 'auto' }}>
                    <Avatar
                      style={{
                        backgroundColor: 'var(--stripe-purple)',
                        cursor: 'pointer',
                        fontFamily: 'var(--font-primary)',
                        fontWeight: 'var(--weight-medium)',
                      }}
                      icon={<UserOutlined />}
                      size="large"
                    >
                      {getUserInitial()}
                    </Avatar>
                    <span className="stripe-username">
                      {currentUser?.username || '用户'}
                    </span>
                    {getRoleTag()}
                  </Space>
                </Dropdown>
              ) : (
                <Button
                  type="primary"
                  icon={<LoginOutlined />}
                  onClick={() => navigate('/login')}
                  className="stripe-btn-primary stripe-btn-sm"
                >
                  登录
                </Button>
              )}
            </Space>
          </div>
        </Header>
        
        {/* Main Content */}
        <Content className="stripe-content">
          <Outlet />
        </Content>
      </AntLayout>
      
      {/* Mobile Drawer Menu */}
      <Drawer
        title="菜单"
        placement="left"
        onClose={() => setMobileMenuOpen(false)}
        open={mobileMenuOpen}
        className="stripe-mobile-drawer"
      >
        <Menu
          mode="vertical"
          selectedKeys={[location.pathname]}
          items={mobileMenuItems}
          onClick={({ key }) => {
            navigate(key)
            setMobileMenuOpen(false)
          }}
        />
      </Drawer>
      
      <ChangePasswordModal
        open={changePasswordModalOpen}
        onClose={() => setChangePasswordModalOpen(false)}
        onSuccess={() => {}}
      />
    </AntLayout>
  )
}

export default Layout
