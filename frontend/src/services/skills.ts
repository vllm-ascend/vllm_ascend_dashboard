import api from './api'

export interface SkillInfo {
  name: string
  description: string
  scope: string | null
  file_path: string
  loaded_at: string
  content_length: number
}

export interface SkillDetail {
  name: string
  description: string
  scope: string | null
  content: string
  file_path: string
  loaded_at: string
}

export const listSkills = async (): Promise<SkillInfo[]> => {
  const response = await api.get('/system/config/skills')
  return response.data
}

export const getSkillDetail = async (skillName: string): Promise<SkillDetail> => {
  const response = await api.get(`/system/config/skills/${skillName}`)
  return response.data
}

export const refreshSkills = async (): Promise<{ success: boolean; message: string; count: number }> => {
  const response = await api.post('/system/config/skills/refresh')
  return response.data
}
