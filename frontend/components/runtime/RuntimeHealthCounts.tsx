import type { HealthSummary } from '@/lib/api/runtime'

// Running and stopped add up to the total; healthy and unhealthy are the
// running services that have a health check.
export function RuntimeHealthCounts({ health }: { health: HealthSummary }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      <span className="text-slate-500">{health.total} services</span>
      {health.running > 0 && (
        <span className="text-slate-300">{health.running} running</span>
      )}
      {health.healthy > 0 && (
        <span className="text-emerald-400">{health.healthy} healthy</span>
      )}
      {health.unhealthy > 0 && (
        <span className="text-red-400">{health.unhealthy} unhealthy</span>
      )}
      {health.stopped > 0 && (
        <span className="text-slate-500">{health.stopped} stopped</span>
      )}
    </div>
  )
}
