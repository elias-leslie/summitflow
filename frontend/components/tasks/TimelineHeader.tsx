import { RefreshCw, Radio } from 'lucide-react'

interface TimelineHeaderProps {
  isConnected: boolean
  error: string | null
  autoConnect: boolean
  onReconnect: () => void
}

export function TimelineHeader({
  isConnected,
  error,
  autoConnect,
  onReconnect,
}: TimelineHeaderProps) {
  return (
    <div className="flex items-center justify-between px-3 py-2.5 bg-slate-900/60 border border-slate-800/50 rounded-t-lg">
      <div className="flex items-center gap-2">
        <Radio className="h-3.5 w-3.5 text-slate-500" />
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
          Execution Timeline
        </h3>
      </div>
      <div className="flex items-center gap-2">
        {isConnected ? (
          <span className="flex items-center gap-1.5 text-xs text-emerald-400 font-medium">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
            Live
          </span>
        ) : error ? (
          <button
            onClick={onReconnect}
            className="flex items-center gap-1.5 text-xs text-amber-400 hover:text-amber-300 transition-colors px-2 py-1 rounded bg-amber-500/10 hover:bg-amber-500/20"
          >
            <RefreshCw className="h-3 w-3" />
            Reconnect
          </button>
        ) : autoConnect ? (
          <span className="flex items-center gap-1.5 text-xs text-slate-500">
            <span className="h-1.5 w-1.5 rounded-full bg-slate-500 animate-pulse" />
            Connecting...
          </span>
        ) : (
          <span className="text-xs text-slate-600 font-medium">History</span>
        )}
      </div>
    </div>
  )
}
