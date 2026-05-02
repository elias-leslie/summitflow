'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Database,
  ExternalLink,
  Play,
  RefreshCw,
  RotateCw,
  Shield,
  Square,
  X,
} from 'lucide-react'
import { type ReactNode, useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import {
  fetchDbWorkbenchStatus,
  startDbWorkbench,
  stopDbWorkbench,
} from '@/lib/api/db-workbench'
import { getErrorMessage } from '@/lib/utils'

interface DatabaseWorkbenchProps {
  projectId: string
  title?: string
  closeHref?: string
  autoStart?: boolean
  stopOnUnmount?: boolean
  toolbarSlot?: ReactNode
}

const queryKey = (projectId: string) => ['db-workbench', projectId] as const

export function DatabaseWorkbench({
  projectId,
  title = projectId,
  closeHref = `/projects/${projectId}?tab=explorer&type=database`,
  autoStart = true,
  stopOnUnmount = false,
  toolbarSlot,
}: DatabaseWorkbenchProps) {
  const queryClient = useQueryClient()
  const [frameKey, setFrameKey] = useState(0)
  const [autoStartAttempted, setAutoStartAttempted] = useState(false)

  const statusQuery = useQuery({
    queryKey: queryKey(projectId),
    queryFn: () => fetchDbWorkbenchStatus(projectId),
    refetchInterval: 10_000,
  })

  const startMutation = useMutation({
    mutationFn: () => startDbWorkbench(projectId, true),
    onSuccess: (status) => {
      queryClient.setQueryData(queryKey(projectId), status)
      setFrameKey((value) => value + 1)
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, 'Failed to start database workbench'))
    },
  })

  const stopMutation = useMutation({
    mutationFn: () => stopDbWorkbench(projectId),
    onSuccess: (status) => {
      queryClient.setQueryData(queryKey(projectId), status)
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, 'Failed to stop database workbench'))
    },
  })

  const status = statusQuery.data
  const isStarting = startMutation.isPending
  const isStopping = stopMutation.isPending
  const isBusy = isStarting || isStopping || statusQuery.isLoading
  const sharedLabel = status?.shared_with
    ? `shared:${status.shared_with}`
    : null

  const closeWorkbench = useCallback(async () => {
    try {
      if (status?.running) {
        const stopped = await stopDbWorkbench(projectId)
        queryClient.setQueryData(queryKey(projectId), stopped)
      }
      window.close()
      window.setTimeout(() => {
        if (!window.closed) {
          window.location.href = closeHref
        }
      }, 250)
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to close database workbench'))
    }
  }, [closeHref, projectId, queryClient, status?.running])

  useEffect(() => {
    if (
      !autoStart ||
      autoStartAttempted ||
      !status ||
      status.running ||
      !status.installed ||
      !status.configured
    ) {
      return
    }
    setAutoStartAttempted(true)
    startMutation.mutate()
  }, [autoStart, autoStartAttempted, startMutation, status])

  useEffect(() => {
    if (!status?.running) return
    const stopOnClose = () => {
      const url = `/api/projects/${projectId}/db-workbench/stop`
      if (!navigator.sendBeacon?.(url)) {
        void fetch(url, { method: 'POST', keepalive: true })
      }
    }
    window.addEventListener('pagehide', stopOnClose)
    return () => {
      window.removeEventListener('pagehide', stopOnClose)
      if (stopOnUnmount) {
        void stopDbWorkbench(projectId)
      }
    }
  }, [projectId, status?.running, stopOnUnmount])

  const errorMessage = statusQuery.error
    ? getErrorMessage(statusQuery.error, 'Database workbench unavailable')
    : startMutation.error
      ? getErrorMessage(startMutation.error, 'Database workbench unavailable')
      : null

  return (
    <div className="flex h-dvh min-h-dvh flex-col overflow-hidden bg-[#05070b]">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-slate-800/80 bg-slate-950/86 px-3 shadow-[0_18px_48px_-38px_rgba(0,0,0,0.95)]">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-md border border-emerald-500/20 bg-emerald-500/10 text-emerald-300">
            <Database className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-slate-100">
              {title}
            </div>
            <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.14em] text-slate-500">
              <Shield className="h-3 w-3 text-emerald-400" />
              {status?.readonly === false ? 'admin' : 'readonly'}
              <span className="text-slate-700">/</span>
              {status?.running ? 'running' : 'stopped'}
              {sharedLabel ? (
                <>
                  <span className="text-slate-700">/</span>
                  {sharedLabel}
                </>
              ) : null}
            </div>
          </div>
        </div>

        {toolbarSlot ? <div className="min-w-0">{toolbarSlot}</div> : null}

        <div className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            title="Refresh status"
            disabled={isBusy}
            onClick={() => statusQuery.refetch()}
            className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-700/70 bg-slate-900/70 text-slate-300 transition-colors hover:border-slate-600 hover:bg-slate-800 disabled:opacity-40"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
          <button
            type="button"
            title="Reload workbench"
            disabled={!status?.running}
            onClick={() => setFrameKey((value) => value + 1)}
            className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-700/70 bg-slate-900/70 text-slate-300 transition-colors hover:border-slate-600 hover:bg-slate-800 disabled:opacity-40"
          >
            <RotateCw className="h-4 w-4" />
          </button>
          {status?.running ? (
            <button
              type="button"
              title="Stop Pgweb"
              disabled={isBusy}
              onClick={() => stopMutation.mutate()}
              className="flex h-8 w-8 items-center justify-center rounded-md border border-rose-500/25 bg-rose-500/10 text-rose-300 transition-colors hover:bg-rose-500/20 disabled:opacity-40"
            >
              <Square className="h-3.5 w-3.5" />
            </button>
          ) : (
            <button
              type="button"
              title="Start Pgweb"
              disabled={
                isBusy ||
                status?.installed === false ||
                status?.configured === false
              }
              onClick={() => startMutation.mutate()}
              className="flex h-8 w-8 items-center justify-center rounded-md border border-emerald-500/25 bg-emerald-500/10 text-emerald-300 transition-colors hover:bg-emerald-500/20 disabled:opacity-40"
            >
              <Play className="h-4 w-4" />
            </button>
          )}
          {status?.proxy_url && (
            <a
              title="Open workbench"
              href={status.proxy_url}
              target="_blank"
              rel="noreferrer"
              className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-700/70 bg-slate-900/70 text-slate-300 transition-colors hover:border-slate-600 hover:bg-slate-800"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
          )}
          <button
            type="button"
            title="Close workbench"
            disabled={isStopping}
            onClick={() => void closeWorkbench()}
            className="flex h-8 w-8 items-center justify-center rounded-md border border-rose-500/25 bg-rose-500/10 text-rose-300 transition-colors hover:bg-rose-500/20 disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {errorMessage && (
        <div className="border-b border-rose-500/20 bg-rose-950/20 px-3 py-2 text-xs text-rose-200">
          {errorMessage}
        </div>
      )}

      <div className="relative min-h-0 flex-1 bg-[#020305]">
        {status?.running ? (
          <iframe
            key={`${status.started_at ?? 'running'}-${frameKey}`}
            title="Pgweb database workbench"
            src={status.proxy_url}
            className="h-full w-full border-0 bg-[#060a0f]"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-xs uppercase tracking-[0.16em] text-slate-500">
            {isStarting
              ? 'starting pgweb'
              : status?.installed === false
                ? 'pgweb not installed'
                : status?.configured === false
                  ? 'no database configured'
                  : 'pgweb stopped'}
          </div>
        )}
      </div>
    </div>
  )
}
