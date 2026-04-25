'use client'

import { MonitorCog, Network, ShieldCheck } from 'lucide-react'

const connectorRows = [
  ['Role', 'Review-only'],
  ['Host', 'Davion-Sidar'],
  ['Profile', 'Dedicated'],
  ['Egress', 'Allowlist pending'],
] as const

export function WindowsBrowserConnectorPanel() {
  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-900/50">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-md border border-cyan-500/20 bg-cyan-500/10">
          <MonitorCog className="h-4 w-4 text-cyan-300" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-slate-100">
              Windows Co-Browser
            </span>
            <span className="rounded-full border border-slate-600 bg-slate-800/60 px-2 py-0.5 text-2xs font-semibold uppercase tracking-[0.14em] text-slate-300">
              Planned
            </span>
          </div>
          <div className="mt-0.5 text-xs text-slate-500">
            Proxmox remains automation primary
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/25 bg-emerald-500/10 px-2 py-1 text-xs text-emerald-100">
            <ShieldCheck className="h-3.5 w-3.5" />
            Isolated profile
          </span>
          <span className="inline-flex items-center gap-1 rounded-md border border-sky-500/25 bg-sky-500/10 px-2 py-1 text-xs text-sky-100">
            <Network className="h-3.5 w-3.5" />
            Reviewable egress
          </span>
        </div>
      </div>
      <div className="grid gap-2 border-t border-slate-800/60 px-4 py-3 md:grid-cols-4">
        {connectorRows.map(([label, value]) => (
          <div
            key={label}
            className="rounded-md border border-slate-800 bg-slate-950/40 px-3 py-2"
          >
            <div className="text-2xs uppercase tracking-[0.14em] text-slate-500">
              {label}
            </div>
            <div className="mt-1 truncate text-xs font-medium text-slate-200">
              {value}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
