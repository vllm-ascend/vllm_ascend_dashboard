import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as alertRulesApi from '../services/alertRules'

export const useAlertRules = () => {
  return useQuery({
    queryKey: ['alert-rules'],
    queryFn: alertRulesApi.getAlertRules,
  })
}

export const useAlertRule = (ruleId: number | null) => {
  return useQuery({
    queryKey: ['alert-rule', ruleId],
    queryFn: () => (ruleId ? alertRulesApi.getAlertRule(ruleId) : Promise.resolve(null)),
    enabled: !!ruleId,
  })
}

export const useCreateAlertRule = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: alertRulesApi.createAlertRule,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
    },
  })
}

export const useUpdateAlertRule = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ ruleId, data }: { ruleId: number; data: alertRulesApi.AlertRuleUpdate }) =>
      alertRulesApi.updateAlertRule(ruleId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
    },
  })
}

export const useDeleteAlertRule = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: alertRulesApi.deleteAlertRule,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
    },
  })
}

export const useAlertRuleHistory = (ruleId: number | null) => {
  return useQuery({
    queryKey: ['alert-rule-history', ruleId],
    queryFn: () => (ruleId ? alertRulesApi.getAlertRuleHistory(ruleId) : Promise.resolve([])),
    enabled: !!ruleId,
  })
}
