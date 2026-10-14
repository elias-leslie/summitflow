'use client'

import { useMutation } from '@tanstack/react-query'
import clsx from 'clsx'
import Link from 'next/link'
import { useState } from 'react'
import { SavedWorkEvidence } from '@/components/snapshots/SavedWorkEvidence'
import {
  checkProjectGitRemote,
  type DevelopmentProjection,
  type GitSyncResponse,
} from '@/lib/api/git'
import { evidenceAge, type Signals, shortSha } from './developmentSignals'
import type { RepoActions } from './ProjectRow'
import { DashboardContent } from './project-row/DashboardContent'
import { PublishResultBlock } from './project-row/PublishResultBlock'
import { SourceLane } from './SourceLane'

const TASKS_SHOWN = 4

export function RowDetails({
  development,
  signals,
  actions,
}: {
  development: DevelopmentProjection
  signals: Signals
  actions: RepoActions
}) {
  const projectId = development.project_id
  const [history, setHistory] = useState(false)
  const [allTasks, setAllTasks] = useState(false)
  const fetchRemote = useMutation({
    mutationFn: () => checkProjectGitRemote(projectId),
    onSuccess: actions.invalidate,
  })
  const busy =
    actions.publish.isPending || actions.pull.isPending || fetchRemote.isPending
  const blockers = development.blockers
  const tasks = allTasks ? blockers.items : blockers.items.slice(0, TASKS_SHOWN)

  return (
    <div className="space-y-4 border-t border-slate-800/70 bg-slate-950/30 px-4 py-3 lg:pl-9">
      <div className="grid gap-x-8 gap-y-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <section aria-label="Source lane">
          <SourceLane development={development} signals={signals} />
        </section>
        <section aria-label="Task blockers" className="min-w-0">
          <h3 className="mb-1.5 text-2xs font-medium uppercase tracking-[0.12em] text-slate-400">
            Tasks needing review
          </h3>
          {blockers.state !== 'available' && (
            <p className="text-xs text-amber-300">
              {blockers.reason || 'Task evidence is partial'}
            </p>
          )}
          {blockers.state === 'available' && blockers.items.length === 0 && (
            <p className="text-xs text-slate-500">No blocked or failed tasks</p>
          )}
          <ul className="space-y-1">
            {tasks.map((task) => (
              <li
                key={task.task_id}
                className="flex min-w-0 items-baseline gap-2 text-xs"
              >
                <span
                  className={clsx(
                    'shrink-0 font-mono text-2xs',
                    task.status === 'failed'
                      ? 'text-rose-300'
                      : 'text-amber-300',
                  )}
                >
                  {task.status}
                </span>
                <span className="min-w-0">
                  <Link
                    href={`/projects/${projectId}?tab=tasks&task=${task.task_id}`}
                    className="line-clamp-1 text-slate-200 hover:text-phosphor-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
                    title={task.title}
                  >
                    {task.title}
                  </Link>
                  {task.reason !== 'Task needs review' && (
                    <span className="line-clamp-1 text-2xs text-slate-500">
                      {task.reason}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
          {blockers.items.length > TASKS_SHOWN && (
            <button
              type="button"
              onClick={() => setAllTasks(!allTasks)}
              className="mt-1 text-2xs text-phosphor-300 hover:text-phosphor-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
            >
              {allTasks
                ? 'Show fewer'
                : `${blockers.items.length - TASKS_SHOWN} more`}
            </button>
          )}
        </section>
      </div>

      <section
        aria-label="Recovery"
        className="flex flex-wrap gap-x-5 gap-y-1 text-xs"
      >
        <RecoveryFact
          label="Capture"
          value={development.recovery.capture}
          extra={
            development.recovery.capture.backup_count
              ? `${development.recovery.capture.backup_count} kept`
              : undefined
          }
        />
        <RecoveryFact label="Offsite" value={development.recovery.offsite} />
        <RecoveryFact
          label="Repo snapshot"
          value={development.recovery.snapshot}
        />
        <RecoveryFact
          label="Restore drill"
          value={development.recovery.restore}
        />
        <SavedWorkEvidence projectId={projectId} compact />
      </section>

      <section
        aria-label="Remote actions"
        className="flex flex-wrap items-center gap-2"
      >
        <button
          type="button"
          className="btn-secondary text-xs"
          disabled={busy}
          onClick={() => fetchRemote.mutate()}
        >
          {fetchRemote.isPending ? 'Refreshing remote…' : 'Refresh remote refs'}
        </button>
        <button
          type="button"
          className="btn-secondary text-xs"
          disabled={busy}
          onClick={() => actions.pull.mutate()}
        >
          {actions.pull.isPending ? 'Pulling…' : 'Pull remote changes'}
        </button>
        <button
          type="button"
          className="btn-secondary text-xs"
          disabled={busy || !signals.canPublish}
          onClick={() => actions.publish.mutate()}
        >
          {actions.publish.isPending
            ? 'Publishing…'
            : 'Publish accepted source'}
        </button>
        <span className="text-2xs text-slate-500">
          {signals.canPublish
            ? `Publishes ${shortSha(development.accepted.source_commit)}; uncommitted edits stay local.`
            : 'Publishing needs full acceptance of the current source.'}
        </span>
        <button
          type="button"
          aria-expanded={history}
          onClick={() => setHistory(!history)}
          className="ml-auto text-xs text-slate-400 hover:text-slate-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
        >
          {history ? 'Hide history' : 'Commits, branches and checkpoints'}
        </button>
      </section>
      <SyncResults result={fetchRemote.data} error={fetchRemote.error} />
      {history && <DashboardContent projectId={projectId} />}
    </div>
  )
}

function RecoveryFact({
  label,
  value,
  extra,
}: {
  label: string
  value: DevelopmentProjection['publication']
  extra?: string
}) {
  const failed = ['failed', 'error'].includes(value.state)
  const missing = value.state === 'unavailable'
  return (
    <span title={value.reason} className="whitespace-nowrap">
      <span className="text-slate-500">{label} </span>
      <span
        className={clsx(
          failed
            ? 'text-rose-300'
            : missing
              ? 'text-slate-500'
              : 'text-slate-200',
        )}
      >
        {missing ? 'none' : value.state.replaceAll('_', ' ')}
      </span>
      {!missing && evidenceAge(value.observed_at) && (
        <span className="text-slate-500">
          {' '}
          {evidenceAge(value.observed_at)}
        </span>
      )}
      {extra && <span className="text-slate-500"> · {extra}</span>}
    </span>
  )
}

export function SyncResults({
  result,
  error,
}: {
  result?: GitSyncResponse
  error: Error | null
}) {
  if (!result && !error) return null
  return (
    <div className="space-y-0.5">
      {error && (
        <p role="alert" className="text-xs text-rose-300">
          {error.message}
        </p>
      )}
      {result?.results.map((row) => (
        <p
          key={row.path}
          role={
            row.status === 'failed' || row.status === 'skipped'
              ? 'alert'
              : 'status'
          }
          className={clsx(
            'text-xs',
            row.status === 'failed'
              ? 'text-rose-300'
              : row.status === 'skipped'
                ? 'text-amber-300'
                : 'text-slate-300',
          )}
        >
          {row.name}: {row.status.replaceAll('_', ' ')}
          {row.error || row.reason ? `: ${row.error || row.reason}` : ''}
        </p>
      ))}
    </div>
  )
}

export function ActionFeedback({ actions }: { actions: RepoActions }) {
  const { pull, publish } = actions
  if (!pull.data && !pull.error && !publish.data && !publish.error) return null
  return (
    <div className="space-y-2 px-4 pb-3 lg:pl-9">
      <SyncResults result={pull.data} error={pull.error} />
      {publish.error && (
        <p role="alert" className="text-xs text-rose-300">
          {publish.error.message}
        </p>
      )}
      {publish.data && <PublishResultBlock result={publish.data} />}
    </div>
  )
}
