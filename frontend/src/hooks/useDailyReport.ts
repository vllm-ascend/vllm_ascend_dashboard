import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as api from '../services/dailyReport'

export const useReportConfig = () => {
  return useQuery({
    queryKey: ['daily-report-config'],
    queryFn: api.getReportConfig,
  })
}

export const useUpdateReportConfig = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.updateReportConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['daily-report-config'] })
    },
  })
}

export const useTriggerReport = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.triggerReport,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['daily-report-history'] })
      queryClient.invalidateQueries({ queryKey: ['daily-report-latest'] })
    },
  })
}

export const useReportHistory = (limit = 20, offset = 0) => {
  return useQuery({
    queryKey: ['daily-report-history', limit, offset],
    queryFn: () => api.getReportHistory(limit, offset),
  })
}

export const useLatestReport = () => {
  return useQuery({
    queryKey: ['daily-report-latest'],
    queryFn: api.getLatestReport,
  })
}

export const useGenerateReportDraft = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.generateReportDraft,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['daily-report-history'] })
      queryClient.invalidateQueries({ queryKey: ['daily-report-latest'] })
    },
  })
}

export const useSendReportDraft = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.sendReportDraft,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['daily-report-history'] })
      queryClient.invalidateQueries({ queryKey: ['daily-report-latest'] })
    },
  })
}
