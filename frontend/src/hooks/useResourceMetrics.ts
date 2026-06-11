import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as metricsApi from '../services/resourceMetrics'

export const useNpuMetrics = (params: {
  cluster_ids?: number[]
  time_range?: string
}) => {
  return useQuery({
    queryKey: ['npu-metrics', params],
    queryFn: () => metricsApi.getNpuMetrics(params),
    refetchInterval: 60000,
    placeholderData: (prev: metricsApi.NpuMetricsResponse | undefined) => prev,
  })
}

export const useResourceMetricsConfig = () => {
  return useQuery({
    queryKey: ['resource-metrics-config'],
    queryFn: metricsApi.getResourceMetricsConfig,
  })
}

export const useUpdateResourceMetricsConfig = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: metricsApi.updateResourceMetricsConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['resource-metrics-config'] })
      queryClient.invalidateQueries({ queryKey: ['npu-metrics'] })
    },
  })
}