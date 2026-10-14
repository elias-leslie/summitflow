'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowDown, ChevronRight, Loader2, Upload } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import {
  type DevelopmentProjection,
  publishProjectChanges,
  pullRepository,
  type RepoStatus,
} from '@/lib/api/git'
import { deriveSignals, type Signals, STAGES } from './developmentSignals'
import { ActionFeedback, RowDetails } from './RowDetails'
import { SignalCell, TONE_STRIP } from './SignalCell'

/** Shared by the row and the column header so cells line up across rows. */
export const ROW_GRID =
  'lg:grid lg:grid-cols-[minmax(11rem,1.4fr)_repeat(6,minmax(0,1fr))_7rem] lg:items-center lg:gap-3'

export function useRepoActions(
  projectId: string,
  signals: Signals,
  dev: DevelopmentProjection,
) {
  const queryClient = useQueryClient()
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['development-status'] })
    queryClient.invalidateQueries({
      queryKey: ['project-dashboard', projectId],
    })
  }
  const publish = useMutation({
    mutationFn: () => {
      if (!signals.canPublish || !dev.accepted.source_commit)
        throw new Error(
          'Current source needs full acceptance before publication',
        )
      return publishProjectChanges(projectId, dev.accepted.source_commit)
    },
    onSuccess: invalidate,
  })
  const pull = useMutation({
    mutationFn: () => pullRepository(projectId),
    onSuccess: invalidate,
  })
  return { publish, pull, invalidate }
}

export type RepoActions = ReturnType<typeof useRepoActions>

export function ProjectRow({
  repo,
  development,
  defaultOpen = false,
}: {
  repo: RepoStatus
  development: DevelopmentProjection
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const signals = deriveSignals(repo, development)
  const actions = useRepoActions(development.project_id, signals, development)
  const busy = actions.publish.isPending || actions.pull.isPending
  const quick: ReactNode[] = []
  if (repo.behind > 0 && repo.ahead === 0)
    quick.push(
      <QuickButton
        key="pull"
        label={`Pull ${repo.name}`}
        disabled={busy}
        pending={actions.pull.isPending}
        icon={<ArrowDown className="h-3 w-3" />}
        onClick={() => actions.pull.mutate()}
      >
        Pull
      </QuickButton>,
    )
  if (
    signals.canPublish &&
    repo.ahead > 0 &&
    development.publication.mode === 'manual'
  )
    quick.push(
      <QuickButton
        key="publish"
        label={`Publish ${repo.name}`}
        disabled={busy}
        pending={actions.publish.isPending}
        icon={<Upload className="h-3 w-3" />}
        onClick={() => actions.publish.mutate()}
      >
        Publish
      </QuickButton>,
    )

  return (
    <article
      aria-label={`${repo.name} development`}
      className={clsx(
        'relative overflow-hidden rounded-md border bg-slate-900/40 transition-colors',
        open
          ? 'border-slate-700/80 bg-slate-900/70'
          : 'border-slate-800/60 hover:border-slate-700/70 hover:bg-slate-900/60',
      )}
    >
      <span
        aria-hidden="true"
        className={clsx(
          'absolute inset-y-0 left-0 w-[3px]',
          TONE_STRIP[signals.worst],
        )}
      />
      <div
        className={clsx(
          'flex flex-wrap items-center gap-x-4 gap-y-1.5 py-2 pl-3 pr-2',
          ROW_GRID,
        )}
      >
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="group flex min-w-0 basis-full items-center gap-2 rounded text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400 lg:basis-auto"
        >
          <ChevronRight
            className={clsx(
              'h-3.5 w-3.5 shrink-0 text-slate-600 transition-transform group-hover:text-slate-300',
              open && 'rotate-90',
            )}
          />
          <span className="truncate text-sm font-semibold text-slate-100">
            {repo.name}
          </span>
          {repo.branch !== 'main' && (
            <span className="truncate font-mono text-2xs text-slate-500">
              {repo.branch}
            </span>
          )}
        </button>
        {STAGES.map((stage) => (
          <SignalCell
            key={stage.key}
            label={stage.label}
            cell={signals.cells[stage.key]}
          />
        ))}
        <div className="ml-auto flex items-center justify-end gap-1.5">
          {quick}
        </div>
      </div>
      <ActionFeedback actions={actions} />
      {open && (
        <RowDetails
          development={development}
          signals={signals}
          actions={actions}
        />
      )}
    </article>
  )
}

function QuickButton({
  label,
  disabled,
  pending,
  icon,
  onClick,
  children,
}: {
  label: string
  disabled: boolean
  pending: boolean
  icon: ReactNode
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex items-center gap-1 rounded border border-cyan-500/25 bg-cyan-500/10 px-2 py-0.5 text-2xs font-medium text-cyan-200 transition-colors hover:border-cyan-400/50 hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
    >
      {pending ? <Loader2 className="h-3 w-3 animate-spin" /> : icon}
      {children}
    </button>
  )
}
