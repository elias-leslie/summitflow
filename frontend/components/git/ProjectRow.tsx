'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { useState } from 'react'
import { SavedWorkEvidence } from '@/components/snapshots/SavedWorkEvidence'
import {
  checkProjectGitRemote,
  type DevelopmentProjection,
  publishProjectChanges,
  pullRepository,
  type RepoStatus,
} from '@/lib/api/git'
import { DevelopmentEvidence, evidenceTime } from './DevelopmentEvidence'
import { DashboardContent } from './project-row/DashboardContent'
import { PublishResultBlock } from './project-row/PublishResultBlock'
import { RemoteStatusBadge } from './RemoteStatusBadge'

export function ProjectRow({
  repo,
  development,
}: {
  repo: RepoStatus
  development: DevelopmentProjection
}) {
  const queryClient = useQueryClient()
  const [remoteCheckedAt, setRemoteCheckedAt] = useState<Date | null>(null)
  const projectId = development.project_id
  const accepted = development.accepted
  const canPublish =
    accepted.state === 'accepted' &&
    accepted.full_coverage === true &&
    !!accepted.source_commit
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['development-status'] })
    queryClient.invalidateQueries({ queryKey: ['git-status'] })
    queryClient.invalidateQueries({
      queryKey: ['project-dashboard', projectId],
    })
  }
  const publish = useMutation({
    mutationFn: () => {
      if (!canPublish || !accepted.source_commit)
        throw new Error(
          'Current source needs full acceptance before publication',
        )
      return publishProjectChanges(projectId, accepted.source_commit)
    },
    onSuccess: invalidate,
  })
  const fetchRemote = useMutation({
    mutationFn: () => checkProjectGitRemote(projectId),
    onSuccess: (result) => {
      if (
        result.results.some(
          (row) => row.status === 'updated' || row.status === 'up_to_date',
        )
      )
        setRemoteCheckedAt(new Date())
      invalidate()
    },
  })
  const pull = useMutation({
    mutationFn: () => pullRepository(projectId),
    onSuccess: invalidate,
  })
  const busy = publish.isPending || fetchRemote.isPending || pull.isPending
  const working = development.working_tree

  return (
    <article
      className="card space-y-4 p-4"
      aria-label={`${repo.name} development`}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-slate-100">
          <Link
            className="hover:text-phosphor-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
            href={`/projects/${projectId}/git`}
          >
            {repo.name}
          </Link>
        </h2>
        <span className="text-xs text-slate-400">
          Local evidence read {evidenceTime(development.observed_at)}
        </span>
      </header>
      <dl className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="space-y-1">
          <dt className="text-xs font-medium text-slate-300">Working tree</dt>
          <dd className="text-sm text-slate-100">
            {working.uncommitted === undefined
              ? working.state
              : `${working.uncommitted} uncommitted ${working.uncommitted === 1 ? 'file' : 'files'}`}
          </dd>
          <dd className="text-xs text-slate-400">
            {working.unpublished === null || working.unpublished === undefined
              ? 'Unpublished count unavailable'
              : `${working.unpublished} unpublished ${working.unpublished === 1 ? 'commit' : 'commits'} against local remote refs`}
          </dd>
          {working.source_commit && (
            <dd className="break-all font-mono text-xs text-slate-300">
              {working.source_commit}
            </dd>
          )}
          {working.state === 'error' && (
            <dd className="text-xs text-rose-300">{working.reason}</dd>
          )}
        </div>
        <DevelopmentEvidence label="Accepted source" evidence={accepted} />
        <DevelopmentEvidence
          label="Running source"
          evidence={development.running}
        />
      </dl>
      <section
        className="border-t border-slate-800 pt-3"
        aria-label="Recovery evidence"
      >
        <h3 className="mb-3 text-xs font-medium text-slate-300">Recovery</h3>
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <SavedWorkEvidence projectId={projectId} />
          <DevelopmentEvidence
            label="Backup capture"
            evidence={development.recovery.capture}
          />
          <DevelopmentEvidence
            label="Offsite copy"
            evidence={development.recovery.offsite}
          />
          <DevelopmentEvidence
            label="Backup repository snapshot"
            evidence={development.recovery.snapshot}
          />
          <DevelopmentEvidence
            label="Restore drill"
            evidence={development.recovery.restore}
          />
        </dl>
      </section>
      <section
        className="border-t border-slate-800 pt-3"
        aria-label="Task blockers"
      >
        <h3 className="text-xs font-medium text-slate-300">Task blockers</h3>
        {development.blockers.state !== 'available' && (
          <p className="mt-1 text-xs text-amber-300">
            {development.blockers.reason || 'Task evidence is partial'}
          </p>
        )}
        {development.blockers.state === 'available' &&
          development.blockers.items.length === 0 && (
            <p className="mt-1 text-xs text-slate-400">
              No blocked or failed tasks recorded
            </p>
          )}
        <ul className="mt-1 space-y-2">
          {development.blockers.items.slice(0, 3).map((task) => (
            <TaskBlocker key={task.task_id} task={task} projectId={projectId} />
          ))}
        </ul>
        {development.blockers.items.length > 3 && (
          <details className="mt-2">
            <summary className="cursor-pointer text-xs text-amber-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400">
              {development.blockers.items.length - 3} more blocked or failed
              tasks
            </summary>
            <ul className="mt-2 space-y-2">
              {development.blockers.items.slice(3).map((task) => (
                <TaskBlocker
                  key={task.task_id}
                  task={task}
                  projectId={projectId}
                />
              ))}
            </ul>
          </details>
        )}
      </section>
      <details className="border-t border-slate-800 pt-3">
        <summary className="cursor-pointer text-sm text-slate-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400">
          Evidence references
        </summary>
        <dl className="mt-3 grid gap-3 text-xs text-slate-400 sm:grid-cols-2">
          {Object.entries({
            acceptance: accepted,
            running: development.running,
            ...development.recovery,
            publication: development.publication,
          }).map(([label, item]) => (
            <div key={label}>
              <dt className="capitalize text-slate-300">{label}</dt>
              <dd className="break-all font-mono">
                {item.evidence || 'No retained artifact'}
              </dd>
              {item.snapshot_id && (
                <dd className="break-all font-mono">
                  Snapshot {item.snapshot_id}
                </dd>
              )}
            </div>
          ))}
        </dl>
      </details>
      <details className="border-t border-slate-800 pt-3">
        <summary className="cursor-pointer text-sm text-slate-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400">
          Branches, checkpoints and history
        </summary>
        <div className="mt-3">
          <DashboardContent projectId={projectId} />
        </div>
      </details>
      <details className="border-t border-slate-800 pt-3">
        <summary className="cursor-pointer text-sm text-slate-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400">
          Publication and remote actions
        </summary>
        <div className="mt-3 space-y-3">
          <dl>
            <DevelopmentEvidence
              label="Last manual publication"
              evidence={development.publication}
            />
          </dl>
          <div className="flex flex-wrap items-center gap-2">
            <RemoteStatusBadge
              ahead={repo.ahead}
              behind={repo.behind}
              branch={repo.branch}
              checkedAt={remoteCheckedAt}
            />
            <button
              type="button"
              className="btn-secondary text-xs"
              disabled={busy}
              onClick={() => fetchRemote.mutate()}
            >
              {fetchRemote.isPending
                ? 'Refreshing remote…'
                : 'Refresh remote refs'}
            </button>
            <button
              type="button"
              className="btn-secondary text-xs"
              disabled={busy}
              onClick={() => pull.mutate()}
            >
              {pull.isPending ? 'Pulling…' : 'Pull remote changes'}
            </button>
            <button
              type="button"
              className="btn-secondary text-xs"
              disabled={busy || !canPublish}
              onClick={() => publish.mutate()}
            >
              {publish.isPending ? 'Publishing…' : 'Publish accepted source'}
            </button>
          </div>
          <p className="text-xs text-slate-400">
            {canPublish
              ? `Publishes ${accepted.source_commit}. Local edits remain uncommitted.`
              : 'Current source needs full acceptance before publication.'}
          </p>
          {[fetchRemote, pull].map((operation, index) => (
            <div key={index}>
              {operation.error && (
                <p role="alert" className="text-sm text-rose-300">
                  {operation.error.message}
                </p>
              )}
              {operation.data?.results.map((row) => (
                <p
                  key={row.path}
                  role={
                    row.status === 'failed' || row.status === 'skipped'
                      ? 'alert'
                      : 'status'
                  }
                  className="text-xs text-slate-300"
                >
                  {row.name}: {row.status.replaceAll('_', ' ')}
                  {row.error || row.reason
                    ? `: ${row.error || row.reason}`
                    : ''}
                </p>
              ))}
            </div>
          ))}
          {publish.error && (
            <p role="alert" className="text-sm text-rose-300">
              {publish.error.message}
            </p>
          )}
          {publish.data && <PublishResultBlock result={publish.data} />}
        </div>
      </details>
    </article>
  )
}

function TaskBlocker({
  task,
  projectId,
}: {
  task: DevelopmentProjection['blockers']['items'][number]
  projectId: string
}) {
  return (
    <li className="text-sm">
      <Link
        className="text-amber-200 underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
        href={`/projects/${projectId}?tab=tasks&task=${task.task_id}`}
      >
        {task.title}
      </Link>
      <span className="ml-2 text-xs text-amber-300">{task.status}</span>
      <p className="text-xs text-slate-400">{task.reason}</p>
    </li>
  )
}
