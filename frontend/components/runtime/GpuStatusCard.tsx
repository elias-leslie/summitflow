'use client'

import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { Cpu } from 'lucide-react'
import { type GpuDevice, type GpuProcess, runtimeApi } from '@/lib/api/runtime'
import { POLL_STANDARD } from '@/lib/polling'

const STATUS_BAR: Record<GpuDevice['status'], string> = {
  ok: 'bg-neon-cyan',
  warning: 'bg-amber-400',
  critical: 'bg-rose-500',
}

const STATUS_TEXT: Record<GpuDevice['status'], string> = {
  ok: 'text-neon-cyan',
  warning: 'text-amber-400',
  critical: 'text-rose-500',
}

function gib(mb: number): string {
  return `${(mb / 1024).toFixed(1)}G`
}

function ProcessRow({ proc }: { proc: GpuProcess }) {
  const isCompute = proc.type === 'compute'
  return (
    <div className="flex items-center gap-2 px-2.5 py-1 text-2xs">
      <span
        className={clsx(
          'rounded px-1 py-0.5 font-medium shrink-0 w-16 text-center',
          isCompute
            ? 'bg-cyan-500/10 text-cyan-400'
            : 'bg-slate-700/50 text-slate-400',
        )}
      >
        {isCompute ? 'compute' : 'display'}
      </span>
      <span className="font-mono tabular-nums text-slate-300 shrink-0 w-16 text-right">
        {proc.used_mb != null ? gib(proc.used_mb) : '-'}
      </span>
      <span className="font-mono text-slate-500 shrink-0 w-12">
        {proc.pid > 0 ? proc.pid : ''}
      </span>
      <span
        className="truncate text-slate-400"
        title={proc.command ?? proc.name}
      >
        {proc.command ?? proc.name}
      </span>
    </div>
  )
}

function DeviceCard({ device }: { device: GpuDevice }) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-slate-900/45 p-3 space-y-2.5">
      {/* Header */}
      <div className="flex items-center gap-2 flex-wrap">
        <Cpu className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
        <span className="text-xs font-medium text-slate-200">
          {device.name}
        </span>
        {device.utilization_percent != null && (
          <span className="text-2xs font-mono text-slate-400">
            {device.utilization_percent}% util
          </span>
        )}
        <span className="ml-auto flex items-center gap-2 text-2xs font-mono text-slate-500">
          {device.temperature_c != null && (
            <span>{device.temperature_c}°C</span>
          )}
          {device.power_draw_w != null && device.power_limit_w != null && (
            <span>
              {Math.round(device.power_draw_w)}/
              {Math.round(device.power_limit_w)}W
            </span>
          )}
        </span>
      </div>

      {/* VRAM bar */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-2xs">
          <span className="text-slate-500 uppercase tracking-wide">VRAM</span>
          <span
            className={clsx(
              'font-mono tabular-nums',
              STATUS_TEXT[device.status],
            )}
          >
            {gib(device.memory_used_mb)} / {gib(device.memory_total_mb)} used ·{' '}
            <span className="text-emerald-400">
              {gib(device.memory_free_mb)} free
            </span>
          </span>
        </div>
        <div className="h-2 bg-slate-800 rounded-full overflow-hidden ring-1 ring-white/[0.03]">
          <div
            className={clsx(
              'h-full rounded-full transition-all duration-700',
              STATUS_BAR[device.status],
            )}
            style={{ width: `${Math.min(device.memory_percent_used, 100)}%` }}
          />
        </div>
      </div>

      {/* Processes — what's using the GPU */}
      {device.processes.length > 0 && (
        <div className="rounded-md border border-slate-800/60 divide-y divide-slate-800/40 overflow-hidden">
          {device.processes.map((proc, i) => (
            <ProcessRow key={`${proc.pid}-${proc.type}-${i}`} proc={proc} />
          ))}
        </div>
      )}
    </div>
  )
}

export function GpuStatusCard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['system', 'gpu'],
    queryFn: runtimeApi.getGpuStatus,
    refetchInterval: POLL_STANDARD,
  })

  // Hide entirely on hosts with no GPU or a probe error — keeps the page clean.
  if (isLoading || error || !data?.available || data.devices.length === 0) {
    return null
  }

  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        <h2 className="display text-sm font-bold uppercase tracking-[0.16em] text-slate-200">
          GPU
        </h2>
        <p className="text-xs text-slate-500">
          Utilization and what&rsquo;s holding VRAM — check free headroom before
          bringing a model online.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {data.devices.map((device) => (
          <DeviceCard key={device.index} device={device} />
        ))}
      </div>
    </section>
  )
}
