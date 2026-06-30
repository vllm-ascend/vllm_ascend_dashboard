import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'

import Login from './pages/Login'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import CIBoard from './pages/CIBoard'
import WorkflowDetail from './pages/WorkflowDetail'
import JobDetail from './pages/JobDetail'
import JobRuns from './pages/JobRuns'
import CIDailyReport from './pages/CIDailyReport'
import Admin from './pages/Admin'
import Models from './pages/Models'
import ModelDetail from './pages/ModelDetail'
import ModelDailyReport from './pages/ModelDailyReport'
import ModelBoardConfig from './pages/ModelBoardConfig'
import CIBoardConfig from './pages/CIBoardConfig'
import GitHubActivityDetail from './pages/GitHubActivityDetail'
import CommitAnalysisDetail from './pages/CommitAnalysisDetail'
import ProjectBoard from './pages/ProjectBoard'
import ProjectBoardConfig from './pages/ProjectBoardConfig'
import PRPipelineBoard from './pages/PRPipelineBoard'
import PRDetail from './pages/PRDetail'
import ResourceDashboard from './pages/ResourceDashboard'
import ResourceDashboardConfig from './pages/ResourceDashboardConfig'
import DailyReportConfigPage from './pages/DailyReportConfig'
import SmtpConfig from './pages/SmtpConfig'
import AlertRulesManagement from './pages/AlertRulesManagement'
import IssueDiagnosis from './pages/IssueDiagnosis'
import Register from './pages/Register'
import UserStats from './pages/UserStats'
import TestObservabilityDashboard from './pages/TestObservabilityDashboard'
import LogCenter from './pages/LogCenter'
import ShareReport from './pages/ShareReport'
import { useCurrentUser } from './hooks/useCurrentUser'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

// 需要登录的路由保护组件
function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('access_token')

  // 首先检查 token 是否存在
  if (!token) {
    return <Navigate to="/login" replace />
  }

  // 使用 React Query 获取最新用户信息
  const { data: currentUser, isLoading, error } = useCurrentUser()

  // 加载中，显示加载状态
  if (isLoading || !currentUser) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <div>加载中...</div>
      </div>
    )
  }

  // 如果获取用户信息失败（可能是 token 过期），重定向到登录页
  if (error || !currentUser) {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

// 仅管理员路由需要登录和权限
function AdminRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('access_token')

  // 首先检查 token 是否存在
  if (!token) {
    return <Navigate to="/login" replace />
  }

  // 使用 React Query 获取最新用户信息
  const { data: currentUser, isLoading, error } = useCurrentUser()

  // 加载中，显示加载状态
  if (isLoading || !currentUser) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <div>加载中...</div>
      </div>
    )
  }

  // 如果获取用户信息失败（可能是 token 过期），重定向到登录页
  if (error || !currentUser) {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    return <Navigate to="/login" replace />
  }

  // 检查用户是否为管理员
  if (currentUser.role !== 'admin' && currentUser.role !== 'super_admin') {
    return <Navigate to="/" replace />
  }

  return <>{children}</>
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN}>
        <BrowserRouter>
          <Routes>
            {/* 公开分享页面 */}
            <Route path="/share/:token" element={<ShareReport />} />
            {/* 登录页面 */}
            <Route path="/login" element={<Login />} />
            {/* 注册页面 */}
            <Route path="/register" element={<Register />} />

            {/* 需要登录的路由（默认） */}
            <Route path="/" element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }>
              <Route index element={<Dashboard />} />
              <Route path="ci" element={<CIBoard />} />
              {/* Project Dashboard */}
              <Route path="project" element={<ProjectBoard />} />
              {/* CI 详情页面 */}
              <Route path="ci/runs/:runId" element={<WorkflowDetail />} />
              <Route path="ci/jobs/:jobId" element={<JobDetail />} />
              <Route path="ci/jobs/:workflowName/:jobName" element={<JobRuns />} />
              {/* CI 每日报告页面 */}
              <Route path="ci/reports/:date" element={<CIDailyReport />} />
              {/* 模型管理页面 */}
              <Route path="models" element={<Models />} />
              <Route path="models/:id" element={<ModelDetail />} />
              <Route path="resources" element={<ResourceDashboard />} />
              {/* 模型每日报告页面 */}
              <Route path="models/reports/:date" element={<ModelDailyReport />} />
              {/* 告警规则 */}
              <Route path="alert-rules" element={<AlertRulesManagement />} />
              {/* 问题定位（管理员） */}
              <Route
                path="issue-diagnosis"
                element={
                  <AdminRoute>
                    <IssueDiagnosis />
                  </AdminRoute>
                }
              />
              {/* 用户统计（管理员） */}
              <Route
                path="user-stats"
                element={
                  <AdminRoute>
                    <UserStats />
                  </AdminRoute>
                }
              />
              {/* GitHub 动态详情页面 */}
              <Route path="github-activity/:project" element={<GitHubActivityDetail />} />
              <Route path="github-activity/:project/commits/:sha" element={<CommitAnalysisDetail />} />
              {/* PR Pipeline Kanban */}
              <Route path="pr-pipeline" element={<PRPipelineBoard />} />
              <Route path="pr-pipeline/:prNumber" element={<PRDetail />} />
              {/* Test Observability Dashboard */}
              <Route path="test-board" element={<TestObservabilityDashboard />} />
              {/* 日志中心（仅开发模式） */}
              {import.meta.env.DEV && <Route path="logs" element={<LogCenter />} />}

              {/* 仅管理员访问的路由 */}
              <Route
                path="admin"
                element={
                  <AdminRoute>
                    <Admin />
                  </AdminRoute>
                }
              />
              {/* CI 看板配置（管理员） */}
              <Route
                path="admin/ci-board-config"
                element={
                  <AdminRoute>
                    <CIBoardConfig />
                  </AdminRoute>
                }
              />
              {/* 模型看板配置（管理员） */}
              <Route
                path="admin/model-board-config"
                element={
                  <AdminRoute>
                    <ModelBoardConfig />
                  </AdminRoute>
                }
              />
              {/* 项目看板配置（管理员） */}
              <Route
                path="admin/project-board-config"
                element={
                  <AdminRoute>
                    <ProjectBoardConfig />
                  </AdminRoute>
                }
              />
              {/* 资源看板配置（管理员） */}
              <Route
                path="admin/resource-dashboard-config"
                element={
                  <AdminRoute>
                    <ResourceDashboardConfig />
                  </AdminRoute>
                }
              />
              {/* SMTP 邮件服务器（管理员） */}
              <Route
                path="admin/smtp-config"
                element={
                  <AdminRoute>
                    <SmtpConfig />
                  </AdminRoute>
                }
              />
              {/* 每日运行报告（管理员） */}
              <Route
                path="admin/daily-report"
                element={
                  <AdminRoute>
                    <DailyReportConfigPage />
                  </AdminRoute>
                }
              />
            </Route>

            {/* 404 重定向 */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ConfigProvider>
    </QueryClientProvider>
  )
}

export default App
