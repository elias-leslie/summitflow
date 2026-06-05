'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { runtimeApi } from '@/lib/api/runtime'

type ServiceAction = 'restart' | 'stop' | 'start' | 'enable' | 'disable'

const actionFns: Record<ServiceAction, (service: string) => Promise<unknown>> =
  {
    restart: (s) => runtimeApi.restart(s),
    stop: (s) => runtimeApi.stop(s),
    start: (s) => runtimeApi.start(s),
    enable: (s) => runtimeApi.enableAutostart(s),
    disable: (s) => runtimeApi.disableAutostart(s),
  }

export function useServiceAction(service: string, action: ServiceAction) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => actionFns[action](service),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['runtime', 'status'] })
      queryClient.invalidateQueries({ queryKey: ['runtime', 'health'] })
    },
  })
}
