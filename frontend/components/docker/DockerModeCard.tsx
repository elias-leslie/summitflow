'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { dockerApi } from '@/lib/api/docker'

function modeBadgeClass(mode: 'dev' | 'prod'): string {
  return mode === 'dev'
    ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-200'
    : 'border-amber-500/30 bg-amber-500/10 text-amber-200'
}

function modeDescription(mode: 'dev' | 'prod'): string {
  return mode === 'dev'
    ? 'Bind mounts and hot reload stay on across the app projects in this stack.'
    : 'Containers run the built image commands without hot reload or host-mounted app code.'
}

function sourceDescription(
  source: 'detected' | 'persisted' | 'default',
): string {
  if (source === 'detected') {
    return 'Mode is being read from the running containers.'
  }
  if (source === 'persisted') {
    return 'Mode is coming from the saved stack preference.'
  }
  return 'Mode is using the default stack preference.'
}

export function DockerModeCard() {
  const queryClient = useQueryClient()
  const [lastRequestedMode, setLastRequestedMode] = useState<
    'dev' | 'prod' | null
  >(null)
  const {
    data: runtime,
    error,
    isLoading,
  } = useQuery({
    queryKey: ['docker', 'runtime'],
    queryFn: dockerApi.getRuntime,
    refetchInterval: 10_000,
  })

  const switchModeMut = useMutation({
    mutationFn: (mode: 'dev' | 'prod') => dockerApi.switchRuntimeMode(mode),
    onMutate: (mode) => {
      setLastRequestedMode(mode)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['docker', 'runtime'] })
      queryClient.invalidateQueries({ queryKey: ['docker', 'status'] })
      queryClient.invalidateQueries({ queryKey: ['docker', 'health'] })
    },
  })

  if (isLoading) {
    return <div className="h-36 animate-pulse rounded-lg bg-neutral-800/40" />
  }

  if (error || !runtime) {
    return (
      <Card className="border-red-500/30 bg-red-950/20">
        <CardHeader>
          <CardTitle className="text-base">Stack Mode</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-red-200">
            {error instanceof Error
              ? error.message
              : 'Docker runtime mode is unavailable.'}
          </p>
        </CardContent>
      </Card>
    )
  }

  const isSwitching = switchModeMut.isPending
  const pendingTarget = isSwitching ? lastRequestedMode : null

  return (
    <Card className="border-slate-700 bg-slate-900/70">
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <CardTitle className="text-base">Stack Mode</CardTitle>
          <p className="mt-1 text-sm text-slate-400">
            Dev is the default for this personal stack so agent sessions stay in
            the hot-reload path unless you explicitly flip back to prod.
          </p>
        </div>
        <div
          className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-[0.16em] ${modeBadgeClass(runtime.current_mode)}`}
        >
          {runtime.current_mode}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
            <p className="text-sm text-slate-200">
              {modeDescription(runtime.current_mode)}
            </p>
            <p className="mt-2 text-xs text-slate-500">
              {sourceDescription(runtime.source)}
            </p>
          </div>
          <div className="grid gap-2 rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-sm text-slate-300 sm:grid-cols-2 md:grid-cols-1">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">
                Stack
              </div>
              <div className="mt-1">
                {runtime.is_running ? 'Running' : 'Stopped'}
              </div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">
                Saved
              </div>
              <div className="mt-1">{runtime.configured_mode}</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">
                Default
              </div>
              <div className="mt-1">{runtime.default_mode}</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">
                Runtime
              </div>
              <div className="mt-1">{runtime.runtime}</div>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => switchModeMut.mutate('dev')}
            disabled={isSwitching || runtime.current_mode === 'dev'}
            className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-sm text-cyan-200 transition hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {pendingTarget === 'dev' ? 'Switching to Dev...' : 'Switch to Dev'}
          </button>
          <button
            onClick={() => switchModeMut.mutate('prod')}
            disabled={isSwitching || runtime.current_mode === 'prod'}
            className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200 transition hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {pendingTarget === 'prod'
              ? 'Switching to Prod...'
              : 'Switch to Prod'}
          </button>
        </div>

        {switchModeMut.isError && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">
            {switchModeMut.error instanceof Error
              ? switchModeMut.error.message
              : 'Mode switch failed.'}
            <div className="mt-1 text-xs text-amber-200/80">
              The dashboard can briefly disconnect while SummitFlow recreates
              its own API and web containers.
            </div>
          </div>
        )}

        {switchModeMut.isSuccess && (
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-100">
            {switchModeMut.data.message}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
