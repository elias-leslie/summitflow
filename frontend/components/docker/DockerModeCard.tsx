'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { type RuntimeModeStatus, runtimeApi } from '@/lib/api/runtime'

function runtimeBadgeClass(runtime: RuntimeModeStatus['runtime']): string {
  if (runtime === 'hybrid') {
    return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
  }
  if (runtime === 'native') {
    return 'border-blue-500/30 bg-blue-500/10 text-blue-200'
  }
  if (runtime === 'docker') {
    return 'border-amber-500/30 bg-amber-500/10 text-amber-200'
  }
  return 'border-slate-500/30 bg-slate-500/10 text-slate-200'
}

function modeDescription(mode: 'dev' | 'prod'): string {
  return mode === 'dev'
    ? 'Bind mounts and hot reload stay on across the app projects in this stack.'
    : 'Containers run the built image commands without hot reload or host-mounted app code.'
}

function sourceDescription(
  runtime: RuntimeModeStatus,
  source: 'detected' | 'persisted' | 'default',
): string {
  if (source === 'detected') {
    return 'Docker mode is being read from the running app containers.'
  }
  if (source === 'persisted') {
    return runtime.runtime === 'docker'
      ? 'Docker mode is coming from the saved stack preference.'
      : 'No app containers are running. This is the saved Docker parity preference.'
  }
  return runtime.runtime === 'docker'
    ? 'Docker mode is using the default stack preference.'
    : 'No app containers are running. This is the default Docker parity preference.'
}

function runtimeDescription(runtime: RuntimeModeStatus): string {
  if (runtime.runtime === 'hybrid') {
    return 'Apps are running natively under systemd --user while PostgreSQL, Redis, and Hatchet stay in Docker.'
  }
  if (runtime.runtime === 'native') {
    return 'Apps are running natively and Docker app containers are not active.'
  }
  if (runtime.runtime === 'docker') {
    return modeDescription(runtime.current_mode)
  }
  return 'The Docker parity stack is stopped. Saved mode controls what the next containerized run should use.'
}

function actionLabel(
  runtime: RuntimeModeStatus,
  mode: 'dev' | 'prod',
): string {
  if (runtime.runtime === 'docker') {
    return mode === 'dev' ? 'Switch to Dev' : 'Switch to Prod'
  }
  return mode === 'dev' ? 'Prefer Docker Dev' : 'Prefer Docker Prod'
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
    queryKey: ['runtime', 'mode'],
    queryFn: runtimeApi.getRuntime,
    refetchInterval: 10_000,
  })

  const switchModeMut = useMutation({
    mutationFn: (mode: 'dev' | 'prod') => runtimeApi.switchRuntimeMode(mode),
    onMutate: (mode) => {
      setLastRequestedMode(mode)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['runtime', 'mode'] })
      queryClient.invalidateQueries({ queryKey: ['runtime', 'status'] })
      queryClient.invalidateQueries({ queryKey: ['runtime', 'health'] })
    },
  })

  if (isLoading) {
    return <div className="h-36 animate-pulse rounded-lg bg-neutral-800/40" />
  }

  if (error || !runtime) {
    return (
      <Card className="border-red-500/30 bg-red-950/20">
        <CardHeader>
          <CardTitle className="text-base">Runtime Mode</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-red-200">
            {error instanceof Error
              ? error.message
              : 'Runtime mode is unavailable.'}
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
          <CardTitle className="text-base">Runtime Mode</CardTitle>
          <p className="mt-1 text-sm text-slate-400">
            Native apps are the default runtime. Container mode here only
            reflects live app containers when the Docker parity stack is
            actually running.
          </p>
        </div>
        <div
          className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-[0.16em] ${runtimeBadgeClass(runtime.runtime)}`}
        >
          {runtime.runtime}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
            <p className="text-sm text-slate-200">
              {runtimeDescription(runtime)}
            </p>
            <p className="mt-2 text-xs text-slate-500">
              {sourceDescription(runtime, runtime.source)}
            </p>
          </div>
          <div className="grid gap-2 rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-sm text-slate-300 sm:grid-cols-2 md:grid-cols-1">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">
                Live Apps
              </div>
              <div className="mt-1">{runtime.apps_runtime}</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">
                Infra
              </div>
              <div className="mt-1">{runtime.infra_runtime}</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">
                Docker Pref
              </div>
              <div className="mt-1">{runtime.configured_mode}</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">
                Default
              </div>
              <div className="mt-1">{runtime.default_mode}</div>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => switchModeMut.mutate('dev')}
            disabled={isSwitching || runtime.configured_mode === 'dev'}
            className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-sm text-cyan-200 transition hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {pendingTarget === 'dev'
              ? runtime.runtime === 'docker'
                ? 'Switching to Dev...'
                : 'Saving Docker Dev...'
              : actionLabel(runtime, 'dev')}
          </button>
          <button
            onClick={() => switchModeMut.mutate('prod')}
            disabled={isSwitching || runtime.configured_mode === 'prod'}
            className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200 transition hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {pendingTarget === 'prod'
              ? runtime.runtime === 'docker'
                ? 'Switching to Prod...'
                : 'Saving Docker Prod...'
              : actionLabel(runtime, 'prod')}
          </button>
        </div>

        {switchModeMut.isError && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">
            {switchModeMut.error instanceof Error
              ? switchModeMut.error.message
              : 'Mode switch failed.'}
            <div className="mt-1 text-xs text-amber-200/80">
              {runtime.runtime === 'docker'
                ? 'The dashboard can briefly disconnect while SummitFlow recreates its own API and web containers.'
                : 'The saved Docker preference was not updated.'}
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
