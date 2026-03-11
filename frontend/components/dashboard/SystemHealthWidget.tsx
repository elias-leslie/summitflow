'use client'

import { Activity, RefreshCw, Cpu, HardDrive, Database } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useSystemStats } from '@/hooks/useSystemStats'

interface SystemHealthWidgetProps {
    className?: string
}

function getStatusColor(status: 'ok' | 'warning' | 'critical'): string {
    switch (status) {
        case 'ok':
            return 'text-neon-cyan bg-neon-cyan'
        case 'warning':
            return 'text-amber-400 bg-amber-400'
        case 'critical':
            return 'text-rose-500 bg-rose-500'
    }
}

function getStatusDotClass(status: 'ok' | 'warning' | 'critical'): string {
    switch (status) {
        case 'ok':
            return 'status-dot healthy animate-pulse'
        case 'warning':
            return 'status-dot warning'
        case 'critical':
            return 'status-dot critical animate-pulse'
    }
}

export function SystemHealthWidget({ className }: SystemHealthWidgetProps) {
    const { data, isLoading, error, refetch, isFetching } = useSystemStats()

    const overallStatus = data
        ? [data.cpu.status, data.memory.status, data.disk.status].includes('critical')
            ? 'critical'
            : [data.cpu.status, data.memory.status, data.disk.status].includes('warning')
                ? 'warning'
                : 'ok'
        : 'ok'

    const statusLabel = overallStatus === 'ok'
        ? 'All Systems Operational'
        : overallStatus === 'warning'
            ? 'Elevated Resource Usage'
            : 'Critical Resource Usage'

    const errorMessage = error instanceof Error ? error.message : 'Failed to load stats'

    return (
        <Card className={cn('card-elevated p-4 flex flex-col gap-4', className)}>
            <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2">
                    <Activity className="w-4 h-4 text-outrun-500" />
                    System Status
                </h3>
                <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 w-6 p-0 rounded-full hover:bg-slate-800"
                    onClick={() => refetch()}
                    disabled={isFetching}
                    aria-label="Refresh system status"
                >
                    <RefreshCw className={cn('w-3.5 h-3.5 text-slate-500 hover:text-outrun-400', isFetching && 'animate-spin')} />
                </Button>
            </div>

            {isLoading ? (
                <div className="flex items-center justify-center py-4">
                    <div className="w-4 h-4 border-2 border-phosphor-500/30 border-t-phosphor-500 rounded-full animate-spin" />
                </div>
            ) : error ? (
                <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-center">
                    <div className="text-xs font-medium text-rose-300">System metrics unavailable</div>
                    <div className="mt-1 text-[11px] text-rose-400/90">{errorMessage}</div>
                </div>
            ) : data ? (
                <>
                    <div className="grid grid-cols-3 gap-3">
                        <div className="flex flex-col gap-1.5">
                            <div className="flex items-center justify-between">
                                <span className="text-xs text-slate-500 flex items-center gap-1">
                                    <Cpu className="w-3 h-3" />
                                    CPU
                                </span>
                                <span className={cn('text-xs font-mono', getStatusColor(data.cpu.status).split(' ')[0])}>
                                    {data.cpu.percent_used}%
                                </span>
                            </div>
                            <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                                <div
                                    className={cn('h-full rounded-full transition-all duration-500', getStatusColor(data.cpu.status).split(' ')[1])}
                                    style={{ width: `${Math.min(data.cpu.percent_used, 100)}%` }}
                                />
                            </div>
                            <span className="text-[10px] text-slate-600 text-center">
                                {data.cpu.cores} cores
                            </span>
                        </div>

                        <div className="flex flex-col gap-1.5">
                            <div className="flex items-center justify-between">
                                <span className="text-xs text-slate-500 flex items-center gap-1">
                                    <HardDrive className="w-3 h-3" />
                                    RAM
                                </span>
                                <span className={cn('text-xs font-mono', getStatusColor(data.memory.status).split(' ')[0])}>
                                    {data.memory.percent_used}%
                                </span>
                            </div>
                            <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                                <div
                                    className={cn('h-full rounded-full transition-all duration-500', getStatusColor(data.memory.status).split(' ')[1])}
                                    style={{ width: `${Math.min(data.memory.percent_used, 100)}%` }}
                                />
                            </div>
                            <span className="text-[10px] text-slate-600 text-center">
                                {data.memory.used_gb.toFixed(1)}/{data.memory.total_gb.toFixed(1)}GB
                            </span>
                        </div>

                        <div className="flex flex-col gap-1.5">
                            <div className="flex items-center justify-between">
                                <span className="text-xs text-slate-500 flex items-center gap-1">
                                    <Database className="w-3 h-3" />
                                    Disk
                                </span>
                                <span className={cn('text-xs font-mono', getStatusColor(data.disk.status).split(' ')[0])}>
                                    {data.disk.percent_used}%
                                </span>
                            </div>
                            <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                                <div
                                    className={cn('h-full rounded-full transition-all duration-500', getStatusColor(data.disk.status).split(' ')[1])}
                                    style={{ width: `${Math.min(data.disk.percent_used, 100)}%` }}
                                />
                            </div>
                            <span className="text-[10px] text-slate-600 text-center">{data.disk.used_gb.toFixed(0)}/{data.disk.total_gb.toFixed(0)}GB</span>
                        </div>
                    </div>

                    <div className="pt-2 mt-auto flex items-center justify-between border-t border-slate-800/50">
                        <span className={cn(
                            'badge-outrun',
                            overallStatus === 'warning' && 'bg-amber-500/20 text-amber-400 border-amber-500/30',
                            overallStatus === 'critical' && 'bg-rose-500/20 text-rose-400 border-rose-500/30'
                        )}>
                            {statusLabel}
                        </span>
                        <div className="flex items-center gap-2">
                            <div className={getStatusDotClass(overallStatus)} />
                            <span
                                className="text-[10px] text-slate-500 uppercase tracking-wider font-mono"
                                title={formatDate(data.timestamp)}
                            >
                                Updated {formatDate(data.timestamp)}
                            </span>
                        </div>
                    </div>
                </>
            ) : null}
        </Card>
    )
}
