import api from './api'

export interface SmtpConfig {
  smtp_host: string
  smtp_port: number
  smtp_username: string
  smtp_use_tls: boolean
  smtp_password_set: boolean
  from_email: string
}

export interface SmtpConfigUpdate {
  smtp_host?: string
  smtp_port?: number
  smtp_username?: string
  smtp_password?: string
  smtp_use_tls?: boolean
  from_email?: string
}

export const getSmtpConfig = async (): Promise<SmtpConfig> => {
  const response = await api.get<SmtpConfig>('/system/config/smtp')
  return response.data
}

export const updateSmtpConfig = async (data: SmtpConfigUpdate): Promise<SmtpConfig> => {
  const response = await api.put<SmtpConfig>('/system/config/smtp', data)
  return response.data
}

export interface SmtpTestResult {
  success: boolean
  message: string
  steps: string[]
}

export const testSmtpConnection = async (): Promise<SmtpTestResult> => {
  const response = await api.post<SmtpTestResult>('/system/config/smtp/test')
  return response.data
}
