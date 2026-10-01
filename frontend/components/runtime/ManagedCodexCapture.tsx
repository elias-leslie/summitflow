'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import {
  controlManagedCodex,
  fetchManagedCodexStatus,
  type ManagedCaptureAction,
  managedEvidenceUrl,
} from '@/lib/api/managed-codex'

const actionLabels: Record<ManagedCaptureAction, string> = {
  disable: 'Disable capture',
  enable: 'Re-enable capture',
  drain: 'Drain delivery queue',
  'check-update': 'Check for Codex update',
  'stage-update': 'Stage update (install)',
  'qualify-update': 'Qualify staged runtime',
  'promote-update': 'Promote staged runtime',
  'rollback-update': 'Rollback runtime',
}
const labels: Record<string, string> = {
  compatible: 'Compatible',
  unsupported: 'Incompatible; rollout fallback',
  unavailable: 'Unavailable',
  rollout_only: 'Rollout recovery only',
  shadow: 'Shadow observations',
  agent_hub_controlled: 'Controlled by Agent Hub',
  accepted: 'Acknowledged by Agent Hub',
  pending: 'Pending',
  disabled: 'Disabled',
  reenable_pending: 'Re-enable pending',
  healthy: 'Healthy',
  initialized: 'Initialized',
  transport_fallback: 'Transport fallback',
  unchecked: 'Not checked',
  available: 'Release checked',
  staged: 'Staged; qualification required',
  qualified: 'Qualified for promotion',
  active: 'Selected for future launches',
  rolled_back: 'Previous runtime restored for future launches',
  failed: 'Update or qualification failed',
}
const display = (value: string) => labels[value] ?? value.replaceAll('_', ' ')
const controlClass =
  'rounded border border-slate-700 px-2.5 py-1.5 text-xs text-slate-200 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:opacity-50'

export function ManagedCodexCapture() {
  const queryClient = useQueryClient()
  const [projectId, setProjectId] = useState<string>()
  const [configuredProjects, setConfiguredProjects] = useState<string[]>([])
  const queryKey = ['runtime', 'managed-codex', projectId ?? null]
  const { data, error, isLoading, isFetching, refetch, dataUpdatedAt } =
    useQuery({
      queryKey,
      queryFn: () => fetchManagedCodexStatus(projectId),
      refetchInterval: 30000,
    })
  useEffect(() => {
    if (data) setConfiguredProjects(data.configured_projects)
  }, [data])
  const action = useMutation({
    mutationFn: (kind: ManagedCaptureAction) => {
      if (
        !data?.available ||
        !data.project_id ||
        (projectId && data.project_id !== projectId) ||
        !data.actions.includes(kind)
      )
        throw new Error('Managed Codex control unavailable')
      return controlManagedCodex(data.project_id, kind)
    },
    onSuccess: (status) => queryClient.setQueryData(queryKey, status),
    onError: () => queryClient.invalidateQueries({ queryKey, exact: true }),
  })

  return (
    <section
      aria-labelledby="managed-codex-heading"
      className="rounded-lg border border-slate-700/60 bg-slate-900/70 px-4 py-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2
            id="managed-codex-heading"
            className="text-sm font-medium text-slate-200"
          >
            Managed Codex capture
          </h2>
          <p className="mt-1 text-xs text-slate-400" role="status">
            {isLoading
              ? 'Checking runtime compatibility...'
              : data
                ? `Installed ${data.installed_version || 'version unknown'} · ${display(data.installed_protocol_status)} · ${data.available ? display(data.health) : 'Managed owner unavailable'}`
                : 'Managed capture status unavailable'}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {configuredProjects.length > 1 && (
            <label className="flex items-center gap-2 text-xs text-slate-400">
              Project
              <select
                value={projectId ?? data?.project_id ?? ''}
                onChange={(event) => {
                  action.reset()
                  setProjectId(event.target.value)
                }}
                disabled={action.isPending}
                className={`${controlClass} max-w-full bg-slate-900`}
              >
                {configuredProjects.map((project) => (
                  <option key={project} value={project}>
                    {project}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button
            type="button"
            onClick={() => {
              action.reset()
              void refetch()
            }}
            disabled={isFetching || action.isPending}
            className={controlClass}
          >
            {isFetching ? 'Checking...' : 'Refresh status'}
          </button>
        </div>
      </div>
      {error && (
        <p className="mt-2 text-xs text-amber-200" role="status">
          {data
            ? 'Status refresh failed. Showing the last loaded snapshot; capture controls are unavailable until refresh succeeds.'
            : 'Owner access or capture status is unavailable. Other runtime services remain available.'}
        </p>
      )}
      {action.error && (
        <p className="mt-2 text-xs text-rose-300" role="alert">
          Managed Codex action failed. Refresh status before retrying.
        </p>
      )}
      {data && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-slate-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">
            Capture and delivery details
          </summary>
          <div className="mt-3 space-y-3 text-xs text-slate-400">
            <p>
              Installed protocol validation applies to the next managed launch.
              Existing sessions retain the runtime versions recorded below.
            </p>
            {data.available ? (
              <>
                <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <div>
                    <dt>Owner process</dt>
                    <dd className="mt-1 text-slate-200">
                      {data.process_active ? 'Active' : 'Inactive'}
                    </dd>
                  </div>
                  <div>
                    <dt>Capture</dt>
                    <dd className="mt-1 text-slate-200">
                      {data.capture_disabled
                        ? 'Disabled'
                        : data.capture_enabled
                          ? 'Enabled'
                          : 'Launch configuration disabled'}
                    </dd>
                  </div>
                  <div>
                    <dt>Delivery</dt>
                    <dd className="mt-1 text-slate-200">
                      {display(data.delivery_health)}
                    </dd>
                  </div>
                  <div>
                    <dt>Projection</dt>
                    <dd className="mt-1 text-slate-200">
                      {display(data.promotion_state)}
                    </dd>
                  </div>
                  <div>
                    <dt>Pending / quarantined records</dt>
                    <dd>
                      {data.pending} / {data.quarantined}
                    </dd>
                  </div>
                  <div>
                    <dt>Capture gaps</dt>
                    <dd>{data.capture_gaps}</dd>
                  </div>
                  <div>
                    <dt>Logical usage / quota (bytes)</dt>
                    <dd>
                      {data.used_bytes} / {data.quota_bytes}
                    </dd>
                  </div>
                  <div>
                    <dt>Physical storage (bytes)</dt>
                    <dd>{data.physical_bytes}</dd>
                  </div>
                </dl>
                <p>
                  Pending {data.pending_bytes} bytes · Quarantined{' '}
                  {data.quarantined_bytes} bytes · Raw retention{' '}
                  {data.raw_retention_seconds} seconds
                </p>
                {data.actions.some((kind) => !kind.endsWith('-update')) &&
                data.project_id ? (
                  <div className="flex flex-wrap items-center gap-2">
                    {data.actions
                      .filter((kind) => !kind.endsWith('-update'))
                      .map((kind) => (
                        <button
                          key={kind}
                          type="button"
                          disabled={action.isPending || isFetching || !!error}
                          onClick={() => action.mutate(kind)}
                          className={controlClass}
                        >
                          {action.isPending && action.variables === kind
                            ? 'Working...'
                            : actionLabels[kind]}
                        </button>
                      ))}
                    <span>Project {data.project_id}</span>
                  </div>
                ) : (
                  <p>
                    Capture controls are unavailable without one verified
                    project binding.
                  </p>
                )}
                <p>
                  Disable pauses new capture while preserving pending delivery
                  and rollout recovery. Drain retries retained delivery.
                  Re-enable resumes at a valid handshake; fallback processes
                  require the next managed launch. These controls do not decide
                  approvals or replay model work.
                </p>
                {data.update && (
                  <div className="space-y-3 border-t border-slate-800 pt-3">
                    <h3 className="font-medium text-slate-200">
                      Codex updates · {display(data.update.state)}
                    </h3>
                    <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                      <div>
                        <dt>Latest checked release</dt>
                        <dd>{data.update.latest_version || 'Unknown'}</dd>
                      </div>
                      <div>
                        <dt>Staged candidate</dt>
                        <dd>
                          {data.update.candidate_version || 'None staged'}
                        </dd>
                      </div>
                      <div>
                        <dt>Selected for future launches</dt>
                        <dd>
                          {data.update.active_version || 'Installed runtime'}
                        </dd>
                      </div>
                      <div>
                        <dt>Rollback runtime</dt>
                        <dd>
                          {data.update.previous_version || 'None recorded'}
                        </dd>
                      </div>
                    </dl>
                    {data.update.error_code && (
                      <p className="text-amber-200" role="status">
                        The last update or qualification failed. Check the
                        recorded versions before retrying.
                      </p>
                    )}
                    {data.project_id &&
                      data.actions.some((kind) => kind.endsWith('-update')) && (
                        <div className="flex flex-wrap gap-2">
                          {data.actions
                            .filter((kind) => kind.endsWith('-update'))
                            .map((kind) => (
                              <button
                                key={kind}
                                type="button"
                                disabled={
                                  action.isPending || isFetching || !!error
                                }
                                onClick={() => action.mutate(kind)}
                                className={controlClass}
                              >
                                {action.isPending && action.variables === kind
                                  ? 'Working...'
                                  : actionLabels[kind]}
                              </button>
                            ))}
                        </div>
                      )}
                    <p>
                      Check reads the official npm release. Stage installs that
                      exact release into private managed storage. Qualification
                      runs an isolated native protocol check and registers a
                      qualified profile with Agent Hub. Promote and rollback
                      change future launches; running sessions keep their pinned
                      runtime.
                    </p>
                  </div>
                )}
                {data.threads.length === 0 ? (
                  <p>No managed session threads recorded.</p>
                ) : (
                  <ul className="space-y-2">
                    {data.threads.map((thread) => {
                      const href = managedEvidenceUrl(
                        data.agent_hub_url,
                        thread.thread_id,
                      )
                      return (
                        <li
                          key={thread.thread_id}
                          className="flex flex-wrap gap-x-3 gap-y-1 border-t border-slate-800 pt-2"
                        >
                          <span className="break-all">
                            {thread.project_id} · {thread.thread_id}
                          </span>
                          <span>
                            Session runtime{' '}
                            {thread.provider_version || 'unknown'}
                          </span>
                          <span>
                            Generation {thread.generation} · Acknowledged
                            position {thread.acknowledged}
                          </span>
                          {href && (
                            <a
                              href={href}
                              target="_blank"
                              rel="noreferrer"
                              className="text-cyan-300 underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
                            >
                              Agent Hub evidence
                            </a>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                )}
              </>
            ) : (
              <p>
                No configured managed capture owner is available. Existing
                external sessions and rollout history remain in Agent Hub.
              </p>
            )}
            <p>
              Agent Hub owns canonical history and checkpoints. Last status
              received{' '}
              {dataUpdatedAt
                ? new Date(dataUpdatedAt).toLocaleString()
                : 'unknown'}
              .
            </p>
          </div>
        </details>
      )}
    </section>
  )
}
