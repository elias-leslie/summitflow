'use client'

import { useQuery } from '@tanstack/react-query'

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
    const response = await fetch('/api/system/stats')
    if (!response.ok) {
        throw new Error('Failed to fetch system stats')
    }
    return response.json()
}

export function useSystemStats() {
    return useQuery({
        queryKey: ['system-stats'],
        queryFn: fetchSystemStats,
        refetchInterval: 5000, // Refresh every 5 seconds
        staleTime: 4000,
    })
}
