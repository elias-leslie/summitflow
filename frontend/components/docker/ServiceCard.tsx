'use client'

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { ContainerStatus } from '@/lib/api/docker'
import { dockerApi } from '@/lib/api/docker'
import { LogViewer } from './LogViewer'

function statusColor(state: string, health: string): string {
  if (health === 'healthy') return 'bg-emerald-500'
  if (health === 'unhealthy') return 'bg-red-500'
  if (state === 'running') return 'bg-amber-500'
  if (state === 'exited') return 'bg-neutral-500'
  return 'bg-neutral-600'
}

function statusLabel(state: string, health: string): string {
  if (health) return health
  return state
}

export function ServiceCard({ container }: { container: ContainerStatus }) {
  const [showLogs, setShowLogs] = useState(false)
  const queryClient = useQueryClient()

  const restartMut = useMutation({
    mutationFn: () => dockerApi.restart(container.service),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['docker', 'status'] })
    },
  })

  const stopMut = useMutation({
    mutationFn: () => dockerApi.stop(container.service),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['docker', 'status'] })
    },
  })

  const startMut = useMutation({
    mutationFn: () => dockerApi.start(container.service),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['docker', 'status'] })
    },
  })

  const isRunning = container.state === 'running'

  return (
    <>
      <div className="rounded-lg border border-neutral-700 bg-neutral-800/50 p-4 hover:border-neutral-600 transition-colors">
        {/* Header */}
        <div className="flex items-center gap-2 mb-3">
          <div
            className={`w-2 h-2 rounded-full ${statusColor(container.state, container.health)}`}
          />
          <span className="font-medium text-white text-sm truncate">
            {container.service}
          </span>
          <span className="ml-auto text-xs text-neutral-500">
            {statusLabel(container.state, container.health)}
          </span>
        </div>

        {/* Ports */}
        {container.ports.length > 0 && (
          <div className="flex gap-1 mb-3 flex-wrap">
            {container.ports.map((p) => (
              <span
                key={p}
                className="text-xs px-1.5 py-0.5 rounded bg-neutral-700 text-neutral-300"
              >
                {p}
              </span>
            ))}
          </div>
        )}

        {/* Status line */}
        <p className="text-xs text-neutral-500 mb-3 truncate">
          {container.status}
        </p>

        {/* Actions */}
        <div className="flex gap-2">
          {isRunning ? (
            <>
              <button
                onClick={() => restartMut.mutate()}
                disabled={restartMut.isPending}
                className="text-xs px-2 py-1 rounded bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 disabled:opacity-50 transition-colors"
              >
                {restartMut.isPending ? '...' : 'Restart'}
              </button>
              <button
                onClick={() => stopMut.mutate()}
                disabled={stopMut.isPending}
                className="text-xs px-2 py-1 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20 disabled:opacity-50 transition-colors"
              >
                {stopMut.isPending ? '...' : 'Stop'}
              </button>
            </>
          ) : (
            <button
              onClick={() => startMut.mutate()}
              disabled={startMut.isPending}
              className="text-xs px-2 py-1 rounded bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-50 transition-colors"
            >
              {startMut.isPending ? '...' : 'Start'}
            </button>
          )}
          <button
            onClick={() => setShowLogs(!showLogs)}
            className="text-xs px-2 py-1 rounded bg-neutral-700 text-neutral-300 hover:bg-neutral-600 transition-colors ml-auto"
          >
            Logs
          </button>
        </div>
      </div>

      {/* Log viewer modal */}
      {showLogs && (
        <LogViewer
          service={container.service}
          onClose={() => setShowLogs(false)}
        />
      )}
    </>
  )
}
