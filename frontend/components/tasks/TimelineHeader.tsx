import { RefreshCw } from 'lucide-react'

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
    <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700">
      <h3 className="text-sm font-medium text-slate-400">Execution Timeline</h3>
      <div className="flex items-center gap-2">
        {isConnected ? (
          <span className="flex items-center gap-1 text-xs text-phosphor-400">
            <span className="w-1.5 h-1.5 bg-phosphor-400 rounded-full animate-pulse" />
            Live
          </span>
        ) : error ? (
          <button
            onClick={onReconnect}
            className="flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300"
          >
            <RefreshCw className="h-3 w-3" />
            Reconnect
          </button>
        ) : autoConnect ? (
          <span className="text-xs text-slate-600">Connecting...</span>
        ) : (
          <span className="text-xs text-slate-600">History</span>
        )}
      </div>
    </div>
  )
}
