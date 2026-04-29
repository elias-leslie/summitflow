'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ExternalLink, RefreshCw } from 'lucide-react'
import { useParams } from 'next/navigation'
import { toast } from 'sonner'
import {
  fetchGraphifyStatus,
  type GraphifyStatus,
  updateGraphify,
} from '@/lib/api/graphify'
import { getErrorMessage } from '@/lib/utils'

function formatDate(value: string | null): string {
  if (!value) return '-'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function stat(label: string, value: number | string): React.ReactElement {
  return (
    <div className="rounded-md border border-slate-800/80 bg-slate-950/60 px-3 py-2">
      <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
        {label}
      </div>
      <div className="mt-1 font-mono text-sm text-slate-200">{value}</div>
    </div>
  )
}

function graphUrl(status: GraphifyStatus): string | null {
  if (!status.html_url) return null
  const stamp = status.html_updated_at ?? status.graph_updated_at ?? ''
  return `${status.html_url}?ts=${encodeURIComponent(stamp)}`
}

export function GraphClient(): React.ReactElement {
  const params = useParams<{ id: string }>()
  const projectId = params.id
  const queryClient = useQueryClient()

  const { data: status, isLoading } = useQuery({
    queryKey: ['graphify-status', projectId],
    queryFn: () => fetchGraphifyStatus(projectId),
  })

  const updateMutation = useMutation({
    mutationFn: () => updateGraphify(projectId),
    onSuccess: () => {
      toast.success('Graph updated')
      queryClient.invalidateQueries({
        queryKey: ['graphify-status', projectId],
      })
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, 'Failed to update graph'))
    },
  })

  if (isLoading || !status) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-cyan-500/30 border-t-cyan-400" />
      </div>
    )
  }

  const url = graphUrl(status)

  return (
    <div className="flex h-full flex-col bg-slate-950">
      <header className="flex-none border-b border-slate-800/80 bg-slate-950/80 px-4 py-3">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-lg font-semibold tracking-tight text-slate-100">
                Graph
              </h1>
              <span className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-cyan-300">
                Graphify
              </span>
            </div>
            <div className="mt-1 max-w-[920px] truncate font-mono text-[11px] text-slate-500">
              {status.root_path}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {status.report_url && (
              <a
                href={status.report_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-700/80 px-3 text-sm text-slate-300 transition-colors hover:border-cyan-500/60 hover:text-cyan-200"
              >
                <ExternalLink className="h-4 w-4" />
                Report
              </a>
            )}
            <button
              type="button"
              onClick={() => updateMutation.mutate()}
              disabled={updateMutation.isPending}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-cyan-500/40 bg-cyan-500/10 px-3 text-sm font-medium text-cyan-200 transition-colors hover:bg-cyan-500/18 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <RefreshCw
                className={
                  updateMutation.isPending ? 'h-4 w-4 animate-spin' : 'h-4 w-4'
                }
              />
              Refresh
            </button>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-5">
          {stat('Nodes', status.node_count.toLocaleString())}
          {stat('Edges', status.edge_count.toLocaleString())}
          {stat('Communities', status.community_count.toLocaleString())}
          {stat('Graph', formatDate(status.graph_updated_at))}
          {stat('HTML', formatDate(status.html_updated_at))}
        </div>
      </header>

      <main className="min-h-0 flex-1">
        {url ? (
          <iframe
            src={url}
            title={`${projectId} graph`}
            className="h-full w-full border-0"
          />
        ) : (
          <div className="flex h-full items-center justify-center p-4">
            <div className="max-w-md rounded-md border border-amber-500/20 bg-amber-500/10 p-5 text-center">
              <AlertTriangle className="mx-auto mb-3 h-8 w-8 text-amber-300" />
              <div className="text-sm font-medium text-amber-100">
                Graph HTML missing
              </div>
              <div className="mt-2 text-sm text-amber-100/70">
                Refresh graph to regenerate the Graphify visualization.
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
