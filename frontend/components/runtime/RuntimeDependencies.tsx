'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { fetchProjects } from '@/lib/api/projects'
import { type DependencyInventoryItem, runtimeApi } from '@/lib/api/runtime'

function version(value: string | null) {
  return value || 'Unknown'
}

const PAGE_SIZE = 50

export function RuntimeDependencies() {
  const queryClient = useQueryClient()
  const [projectId, setProjectId] = useState('summitflow')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [decision, setDecision] = useState<'update' | 'hold' | 'investigate'>(
    'investigate',
  )
  const [reason, setReason] = useState('')
  const [recommendedVersion, setRecommendedVersion] = useState('')
  const [queueTask, setQueueTask] = useState(false)
  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: fetchProjects,
  })
  const { data, isLoading, error } = useQuery({
    queryKey: ['runtime', 'dependencies', projectId, search, page],
    queryFn: () =>
      runtimeApi.getDependencies(projectId, {
        query: search || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
  })
  const selected = data?.items.find((item) => item.entry_path === selectedPath)
  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: ['runtime', 'dependencies', projectId],
    })
  const review = useMutation({
    mutationFn: (item: DependencyInventoryItem) =>
      runtimeApi.reviewDependency(projectId, item.entry_path),
    onSuccess: invalidate,
  })
  const record = useMutation({
    mutationFn: () =>
      runtimeApi.recordDependencyDecision(projectId, {
        entry_path: selectedPath || '',
        decision,
        rationale: reason.trim(),
        expected_revision: selected?.review?.revision || 0,
        recommended_version:
          decision === 'update' ? recommendedVersion.trim() : undefined,
        queue_task: decision === 'update' && queueTask,
      }),
    onSuccess: () => {
      setReason('')
      setQueueTask(false)
      invalidate()
    },
  })

  return (
    <section className="space-y-4" aria-label="Dependencies">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm text-slate-400">
          Project
          <select
            className="ml-2 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-200"
            value={projectId}
            onChange={(event) => {
              setProjectId(event.target.value)
              setSelectedPath(null)
              setPage(0)
            }}
          >
            {(projects || [{ id: 'summitflow', name: 'SummitFlow' }]).map(
              (project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ),
            )}
          </select>
        </label>
        <input
          aria-label="Search packages"
          className="rounded border border-slate-700 bg-slate-900 px-3 py-1 text-sm text-slate-200"
          placeholder="Search packages"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setSelectedPath(null)
            setPage(0)
          }}
        />
        {data && (
          <span className="text-sm text-slate-500">
            {data.total} dependencies
          </span>
        )}
      </div>
      {isLoading && (
        <p className="text-sm text-slate-400">Loading dependencies…</p>
      )}
      {error && (
        <p className="text-sm text-rose-300">
          Dependency inventory is unavailable.
        </p>
      )}
      {data && data.items.length === 0 && (
        <p className="text-sm text-slate-400">
          No dependencies found for this project.
        </p>
      )}
      {data && data.items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-700/60">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-900 text-xs text-slate-400">
              <tr>
                {[
                  'Package',
                  'Declared',
                  'Locked',
                  'Installed',
                  'Latest',
                  'Recommended',
                  'Review',
                ].map((label) => (
                  <th key={label} className="px-3 py-2 font-medium">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {data.items.map((item) => (
                <tr
                  key={item.entry_path}
                  className={
                    selectedPath === item.entry_path
                      ? 'bg-slate-800/70'
                      : 'bg-slate-900/40'
                  }
                >
                  <td className="px-3 py-2">
                    <button
                      className="text-left text-cyan-300 hover:underline"
                      onClick={() => setSelectedPath(item.entry_path)}
                    >
                      {item.name}
                    </button>
                    <span className="block text-xs text-slate-500">
                      {item.ecosystem} · {item.kind} · {item.relationship}
                    </span>
                  </td>
                  {[
                    item.declared_version,
                    item.locked_version,
                    item.installed_version,
                    item.latest_version,
                    item.recommended_version,
                  ].map((value, index) => (
                    <td
                      key={index}
                      className="px-3 py-2 font-mono text-xs text-slate-300"
                    >
                      {version(value)}
                    </td>
                  ))}
                  <td className="px-3 py-2 text-slate-300">
                    {item.review?.decision || 'Unreviewed'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm text-slate-400">
          <span>
            Showing {page * PAGE_SIZE + 1}–
            {Math.min((page + 1) * PAGE_SIZE, data.total)} of {data.total}
          </span>
          <div className="flex gap-2">
            <button
              className="rounded border border-slate-700 px-3 py-1 disabled:opacity-50"
              disabled={page === 0}
              onClick={() => {
                setSelectedPath(null)
                setPage(page - 1)
              }}
            >
              Previous
            </button>
            <button
              className="rounded border border-slate-700 px-3 py-1 disabled:opacity-50"
              disabled={(page + 1) * PAGE_SIZE >= data.total}
              onClick={() => {
                setSelectedPath(null)
                setPage(page + 1)
              }}
            >
              Next
            </button>
          </div>
        </div>
      )}
      {selected && (
        <div className="space-y-3 rounded-lg border border-slate-700/60 bg-slate-900/60 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold text-slate-100">{selected.name}</h2>
              <p className="text-xs text-slate-500">
                {selected.entry_path} · {selected.owner} ·{' '}
                {selected.environment}
              </p>
            </div>
            <button
              className="rounded border border-cyan-700 px-3 py-1 text-sm text-cyan-300 disabled:opacity-50"
              onClick={() => review.mutate(selected)}
              disabled={review.isPending}
            >
              {review.isPending ? 'Checking…' : 'Review evidence'}
            </button>
          </div>
          <div className="grid gap-1 text-xs text-slate-400 sm:grid-cols-3">
            <span>Source: {selected.source_file || 'Unknown'}</span>
            <span>
              Scanned:{' '}
              {selected.last_scanned_at
                ? new Date(selected.last_scanned_at).toLocaleString()
                : 'Unknown'}
            </span>
            <span>Advisory check: {selected.checks.advisories}</span>
          </div>
          {selected.advisories.length > 0 && (
            <ul className="list-disc pl-5 text-sm text-amber-300">
              {selected.advisories.map((advisory) => (
                <li key={advisory}>{advisory}</li>
              ))}
            </ul>
          )}
          {selected.review?.evidence.hosted_proposals?.map((proposal) => (
            <a
              key={proposal.url}
              href={proposal.url}
              target="_blank"
              rel="noopener noreferrer"
              className="block text-sm text-cyan-300 underline"
            >
              {proposal.engine} #{proposal.number}: {proposal.title}
            </a>
          ))}
          {selected.review?.task_id && (
            <p className="text-xs text-slate-400">
              Queued task: {selected.review.task_id}
            </p>
          )}
          {selected.review && (
            <form
              className="flex flex-wrap items-end gap-2 border-t border-slate-800 pt-3"
              onSubmit={(event) => {
                event.preventDefault()
                record.mutate()
              }}
            >
              <label className="text-xs text-slate-400">
                Decision
                <select
                  className="mt-1 block rounded border border-slate-700 bg-slate-900 p-2 text-slate-200"
                  value={decision}
                  onChange={(event) =>
                    setDecision(event.target.value as typeof decision)
                  }
                >
                  <option value="investigate">Investigate</option>
                  <option value="hold">Hold</option>
                  <option value="update">Update</option>
                </select>
              </label>
              {decision === 'update' && (
                <label className="text-xs text-slate-400">
                  Recommended version
                  <input
                    className="mt-1 block rounded border border-slate-700 bg-slate-900 p-2 text-slate-200"
                    value={recommendedVersion}
                    onChange={(event) =>
                      setRecommendedVersion(event.target.value)
                    }
                    required
                  />
                </label>
              )}
              <label className="min-w-48 flex-1 text-xs text-slate-400">
                Reason
                <input
                  className="mt-1 block w-full rounded border border-slate-700 bg-slate-900 p-2 text-slate-200"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  required
                />
              </label>
              {decision === 'update' && (
                <label className="text-xs text-slate-400">
                  <input
                    type="checkbox"
                    checked={queueTask}
                    onChange={(event) => setQueueTask(event.target.checked)}
                  />{' '}
                  Queue task
                </label>
              )}
              <button
                type="submit"
                className="rounded bg-cyan-700 px-3 py-2 text-sm text-white disabled:opacity-50"
                disabled={record.isPending}
              >
                Save decision
              </button>
            </form>
          )}
          {(review.error || record.error) && (
            <p className="text-sm text-rose-300">
              Could not save this review. Refresh the evidence and try again.
            </p>
          )}
        </div>
      )}
    </section>
  )
}
