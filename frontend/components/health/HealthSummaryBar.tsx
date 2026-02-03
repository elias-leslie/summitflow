import { ExternalLink, Zap } from 'lucide-react'
import type { HealthSummary } from './HealthTypes'

interface HealthSummaryBarProps {
  health: HealthSummary | undefined
  fixedToday: number
  inProgress: number
  escalated: number
  autoFixRate: number
}

export function HealthSummaryBar({
  health,
  fixedToday,
  inProgress,
  escalated,
  autoFixRate,
}: HealthSummaryBarProps) {
  return (
    <div className="card rounded-xl p-5">
      <div className="flex items-center gap-8 flex-wrap">
        {/* Status Indicator */}
        <div className="flex items-center gap-3 pr-8 border-r border-slate-700">
          <div
            className={`w-4 h-4 rounded-full ${health?.overall_pass ? 'bg-emerald-500 shadow-[0_0_20px_rgba(16,185,129,0.3)]' : 'bg-rose-500 shadow-[0_0_20px_rgba(244,63,94,0.3)]'} animate-pulse`}
          />
          <div>
            <div
              className={`font-semibold text-lg ${health?.overall_pass ? 'text-emerald-400' : 'text-rose-400'}`}
            >
              {health?.overall_pass ? 'HEALTHY' : 'FAILING'}
            </div>
            <div className="text-slate-500 text-xs">
              {health?.overall_pass
                ? 'All checks passing'
                : `${health?.total_unfixed ?? 0} unfixed errors`}
            </div>
          </div>
        </div>

        {/* Metrics */}
        <div className="flex gap-6 flex-1">
          <div className="text-center">
            <div className="text-2xl font-bold text-emerald-400 tabular-nums">
              {fixedToday}
            </div>
            <div className="text-xs text-slate-500">Fixed Today</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-amber-400 tabular-nums">
              {inProgress}
            </div>
            <div className="text-xs text-slate-500">In Progress</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-rose-400 tabular-nums">
              {escalated}
            </div>
            <div className="text-xs text-slate-500">Escalated</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-purple-400 tabular-nums">
              -
            </div>
            <div className="text-xs text-slate-500">Patterns</div>
          </div>
        </div>

        {/* Success Rate */}
        <div className="text-center px-6 border-l border-slate-700">
          <div className="text-2xl font-bold text-cyan-400 tabular-nums">
            {autoFixRate}%
          </div>
          <div className="text-xs text-slate-500">Auto-Fix Rate</div>
        </div>

        {/* Agent Hub Link */}
        <a
          href="http://localhost:8003"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 px-4 py-2 bg-purple-600/20 text-purple-400 rounded-lg border border-purple-500/30 hover:bg-purple-600/30 transition"
        >
          <Zap className="w-4 h-4" />
          <span className="text-sm font-medium">Memory</span>
          <ExternalLink className="w-3 h-3" />
        </a>
      </div>
    </div>
  )
}
