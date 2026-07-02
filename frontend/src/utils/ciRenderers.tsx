import { Tag } from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  SyncOutlined,
} from '@ant-design/icons'

/**
 * Render status tag for CI workflow/job status - Stripe Design System
 */
export const renderStatusTag = (status: string) => {
  const statusMap: Record<string, { color: string; icon: JSX.Element; text: string }> = {
    completed: { color: '#1890ff', icon: <CheckCircleOutlined />, text: '已完成' },
    in_progress: { color: '#1890ff', icon: <SyncOutlined spin />, text: '进行中' },
    queued: { color: '#64748d', icon: <ClockCircleOutlined />, text: '等待中' },
  }
  const config = statusMap[status] || { color: '#64748d', icon: <ClockCircleOutlined />, text: status }
  return (
    <Tag
      color={config.color}
      icon={config.icon}
      className="stripe-ci-tag"
    >
      {config.text}
    </Tag>
  )
}

/**
 * Render conclusion tag for CI workflow/job conclusion
 * Handles all possible conclusion values from GitHub Actions - Stripe Design System
 */
export const renderConclusionTag = (conclusion: string | null) => {
  if (!conclusion) return <span className="stripe-ci-empty">-</span>

  const conclusionMap: Record<string, { color: string; icon: JSX.Element; text: string }> = {
    success: { color: '#15be53', icon: <CheckCircleOutlined />, text: '成功' },
    failure: { color: '#ff4d4f', icon: <CloseCircleOutlined />, text: '失败' },
    cancelled: { color: '#faad14', icon: <ClockCircleOutlined />, text: '已取消' },
    skipped: { color: '#64748d', icon: <ClockCircleOutlined />, text: '已跳过' },
    timed_out: { color: '#ff4d4f', icon: <CloseCircleOutlined />, text: '超时' },
    action_required: { color: '#faad14', icon: <ClockCircleOutlined />, text: '需处理' },
    stale: { color: '#64748d', icon: <ClockCircleOutlined />, text: '已过期' },
    startup_failure: { color: '#ff4d4f', icon: <CloseCircleOutlined />, text: '启动失败' },
    neutral: { color: '#64748d', icon: <ClockCircleOutlined />, text: '中性' },
  }
  const config = conclusionMap[conclusion] || { color: '#64748d', icon: <ClockCircleOutlined />, text: conclusion }
  return (
    <Tag
      color={config.color}
      icon={config.icon}
      className="stripe-ci-tag"
    >
      {config.text}
    </Tag>
  )
}

/**
 * Format duration in seconds to human-readable string - Stripe Design System
 */
export const formatDuration = (seconds: number | null) => {
  if (!seconds || seconds < 0) return '-'
  // 取整到秒
  const secs = Math.round(seconds)
  const hours = Math.floor(secs / 3600)
  const minutes = Math.floor((secs % 3600) / 60)
  const remainingSecs = secs % 60

  if (hours > 0) {
    return `${hours}h ${minutes}m`
  }
  if (minutes > 0) {
    return `${minutes}m ${remainingSecs}s`
  }
  return `${remainingSecs}s`
}

/**
 * Render hardware tag with consistent colors - Stripe Design System
 */
export const renderHardwareTag = (hardware: string | null) => {
  if (!hardware || hardware === 'unknown') return '-'
  const colorMap: Record<string, string> = {
    A2: '#15be53',
    A3: '#1890ff',
    '310P': '#faad14',
  }
  const color = colorMap[hardware] || '#64748d'
  return (
    <Tag color={color} className="stripe-hardware-tag">
      {hardware}
    </Tag>
  )
}
