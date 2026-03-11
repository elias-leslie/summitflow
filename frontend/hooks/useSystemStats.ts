'use client'

import { useQuery } from '@tanstack/react-query'
import { fetchWithErrorHandling } from '@/lib/api'
import { POLL_FAST, STALE_FAST } from '@/lib/polling'

interface DiskUsage {
    total_gb: number
    used_gb: number
    free_gb: number
    percent_used: number
    status: 'ok' | 'warning' | 'critical'
}

interface MemoryUsage {
    total_gb: number
    used_gb: number
    available_gb: number
    percent_used: number
    status: 'ok' | 'warning' | 'critical'
}

interface CpuUsage {
    percent_used: number
    cores: number
    status: 'ok' | 'warning' | 'critical'
}

export interface SystemStats {
    disk: DiskUsage
    memory: MemoryUsage
    cpu: CpuUsage
    timestamp: string
}

async function fetchSystemStats(): Promise<SystemStats> {
    return fetchWithErrorHandling<SystemStats>('/api/system/stats', {
        errorMessage: 'Failed to fetch system stats',
    })
}

export function useSystemStats() {
    return useQuery({
        queryKey: ['system-stats'],
        queryFn: fetchSystemStats,
        refetchInterval: POLL_FAST,
        staleTime: STALE_FAST,
    })
}
