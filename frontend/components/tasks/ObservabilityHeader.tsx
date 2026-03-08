'use client'

import { GitBranch, List, Play, Radio, RefreshCw } from 'lucide-react'
import type { AgentHubSessionSummary } from '@/lib/api/tasks'

type ViewMode = 'timeline' | 'spans' | 'replay'

interface ObservabilityHeaderProps {
  viewMode: ViewMode
  sessionIds: string[]
  sessions: AgentHubSessionSummary[]
  isLive: boolean
  isLoading: boolean
  onViewModeChange: (mode: ViewMode) => void
  onRefresh: () => void
}

export function ObservabilityHeader({
  viewMode,
  sessionIds,
  sessions,
  isLive,
  isLoading,
  onViewModeChange,
  onRefresh,
}: ObservabilityHeaderProps) {
  return (
    <div className="flex items-center justify-between px-3 py-2.5 bg-slate-900/60 border border-slate-800/50 rounded-t-lg">
      <div className="flex items-center gap-2">
        <Radio className="h-3.5 w-3.5 text-slate-500" />
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
          Agent Observability
        </h3>
        {sessionIds.length > 0 && (
          <span className="text-2xs px-1.5 py-0.5 bg-slate-800 text-slate-500 rounded">
            {sessionIds.length} session{sessionIds.length !== 1 ? 's' : ''}
          </span>
        )}
        {sessions.slice(0, 2).map((session) => {
          const live = session.live_activity
          const label = live
            ? `${live.health} · ${live.phase}`
            : session.status
          return (
            <span
              key={session.id}
              className="text-2xs px-1.5 py-0.5 bg-slate-800 text-slate-400 rounded font-mono"
              title={live?.summary || session.effective_model || session.id}
            >
              {(session.effective_model || session.requested_model || session.id).split('/').pop()} {label}
            </span>
          )
        })}
      </div>

      <div className="flex items-center gap-2">
        {/* View mode tabs */}
        <div className="flex items-center bg-slate-800/60 rounded-md p-0.5">
          {([
            { mode: 'timeline' as const, icon: List, label: 'Timeline' },
            { mode: 'spans' as const, icon: GitBranch, label: 'Spans' },
            { mode: 'replay' as const, icon: Play, label: 'Replay' },
          ]).map(({ mode, icon: Icon, label }) => (
            <button
              key={mode}
              onClick={() => onViewModeChange(mode)}
              className={`flex items-center gap-1 px-2 py-1 rounded text-2xs font-medium transition-colors ${
                viewMode === mode
                  ? 'bg-slate-700 text-slate-200'
                  : 'text-slate-500 hover:text-slate-400'
              }`}
              title={label}
            >
              <Icon className="h-3 w-3" />
              <span className="hidden sm:inline">{label}</span>
            </button>
          ))}
        </div>

        {isLive && (
          <span className="flex items-center gap-1.5 text-xs text-emerald-400 font-medium">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
            Live
          </span>
        )}
        <button
          onClick={onRefresh}
          disabled={isLoading}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-300 px-2 py-1 rounded bg-slate-800/50 hover:bg-slate-700/50 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`h-3 w-3 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>
    </div>
  )
}
