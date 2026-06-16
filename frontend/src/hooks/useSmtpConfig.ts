import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as smtpApi from '../services/smtpConfig'

export const useSmtpConfig = () => {
  return useQuery({
    queryKey: ['smtp-config'],
    queryFn: smtpApi.getSmtpConfig,
  })
}

export const useUpdateSmtpConfig = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: smtpApi.updateSmtpConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['smtp-config'] })
    },
  })
}
