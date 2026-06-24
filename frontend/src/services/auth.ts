import api from './api'

export interface LoginRequest {
  username: string
  password: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface UserResponse {
  id: number
  username: string
  email: string | null
  role: string
  is_active: boolean
  created_at: string
}

export interface RegisterRequest {
  username: string
  email: string
  password: string
}

export interface LoginStatsResponse {
  total_users: number
  active_users_today: number
  active_users_7days: number
  active_users_30days: number
  login_trend: Array<{ date: string; count: number }>
  top_users_by_login_count: Array<{ user_id: number; username: string; login_count: number }>
}

export interface FeatureUsageStatsResponse {
  total_requests: number
  feature_ranking: Array<{ feature_name: string; count: number }>
  user_activity_ranking: Array<{ user_id: number; username: string; count: number }>
  daily_trend: Array<{ date: string; count: number }>
}

export const login = async (data: LoginRequest): Promise<TokenResponse> => {
  const response = await api.post<TokenResponse>('/auth/login', data)
  return response.data
}

export const getCurrentUser = async (): Promise<UserResponse> => {
  const response = await api.get<UserResponse>('/auth/me')
  return response.data
}

export const logout = async (): Promise<{ message: string }> => {
  const response = await api.post<{ message: string }>('/auth/logout')
  return response.data
}

export const refreshToken = async (refreshToken: string): Promise<TokenResponse> => {
  const response = await api.post<TokenResponse>('/auth/refresh', null, {
    headers: {
      Authorization: `Bearer ${refreshToken}`,
    },
  })
  return response.data
}

export const changePassword = async (data: { old_password: string; new_password: string }): Promise<{ message: string }> => {
  const response = await api.post<{ message: string }>('/auth/change-password', data)
  return response.data
}

export const register = async (data: RegisterRequest): Promise<UserResponse> => {
  const response = await api.post<UserResponse>('/auth/register', data)
  return response.data
}

export const getLoginStats = async (days: number = 30): Promise<LoginStatsResponse> => {
  const response = await api.get<LoginStatsResponse>(`/stats/login?days=${days}`)
  return response.data
}

export const getFeatureUsageStats = async (days: number = 30): Promise<FeatureUsageStatsResponse> => {
  const response = await api.get<FeatureUsageStatsResponse>(`/stats/feature-usage?days=${days}`)
  return response.data
}
