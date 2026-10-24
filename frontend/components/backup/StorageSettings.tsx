'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { CheckCircle2, Loader2, Wifi, XCircle } from 'lucide-react'
import { useState } from 'react'
import {
  fetchStorageBackends,
  type StorageBackend,
  testStorageBackend,
  updateStorageBackend,
} from '@/lib/api/backups'
import { formatDate } from '@/lib/format'
import { DetailValue } from './StatusBlock'

const RESTIC_SWITCHES = [
  {
    key: 'restic_automatic_maintenance',
    label: 'Automatic checks and expiry',
    help: 'Daily expiry, weekly prune and repository checks. Off also stops their alerts.',
  },
  {
    key: 'restic_offsite_prune_qualified',
    label: 'Expire old points on Google Drive',
    help: 'Off keeps every point on Drive; the T7 still expires on schedule.',
  },
] as const

function text(config: Record<string, unknown>, key: string): string | null {
  const value = config[key]
  return typeof value === 'string' && value ? value : null
}

function BackendTest({ backend }: { backend: StorageBackend }) {
  const queryClient = useQueryClient()
  const test = useMutation({
    mutationFn: () => testStorageBackend(backend.id),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: ['storage-backends'] }),
  })
  const result =
    test.data ??
    (test.error ? { success: false, message: 'Test request failed' } : null)
  const lastOk = result?.success ?? backend.last_test_ok
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={() => test.mutate()}
        disabled={test.isPending}
        className="flex items-center gap-1.5 rounded bg-slate-700/50 px-2 py-1 text-2xs text-slate-300 transition-colors hover:bg-slate-700/80 disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
      >
        {test.isPending ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <Wifi className="h-3 w-3" />
        )}
        Test access
      </button>
      {(result || backend.last_test_at) && (
        <span
          className={clsx(
            'flex items-center gap-1 text-2xs',
            lastOk ? 'text-emerald-300' : 'text-rose-300',
          )}
        >
          {lastOk ? (
            <CheckCircle2 className="h-3 w-3" />
          ) : (
            <XCircle className="h-3 w-3" />
          )}
          {result
            ? result.message
            : `${lastOk ? 'Passed' : 'Failed'} ${formatDate(backend.last_test_at)}`}
        </span>
      )}
    </div>
  )
}

function ResticBackend({
  backend,
  proxmoxConfigured,
}: {
  backend: StorageBackend
  proxmoxConfigured: boolean
}) {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: (config: Record<string, unknown>) =>
      updateStorageBackend(backend.id, { config }),
    onMutate: () => setError(null),
    onError: (err) =>
      setError(err instanceof Error ? err.message : 'Could not save'),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: ['storage-backends'] }),
  })
  const config = backend.config
  return (
    <div className="space-y-3">
      <dl className="grid gap-3 sm:grid-cols-3">
        <DetailValue
          label="1. T7 repository"
          value={text(config, 'restic_local_repository') ?? 'Not set'}
          mono
        />
        <DetailValue
          label="2. Google Drive repository"
          value={text(config, 'restic_remote_repository') ?? 'Not set'}
          mono
        />
        <DetailValue
          label="3. Proxmox copy"
          value={
            proxmoxConfigured
              ? 'Append-only copy of the T7 repository'
              : 'Not set up'
          }
        />
      </dl>
      <fieldset className="space-y-2">
        <legend className="sr-only">Repository maintenance</legend>
        {RESTIC_SWITCHES.map((item) => {
          const on = config[item.key] !== false
          return (
            <label key={item.key} className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={on}
                disabled={save.isPending}
                onChange={(event) =>
                  save.mutate({ ...config, [item.key]: event.target.checked })
                }
                className="mt-0.5 accent-phosphor-500"
              />
              <span>
                <span className="text-slate-200">{item.label}</span>
                <span className="block text-2xs text-slate-500">
                  {item.help}
                </span>
              </span>
            </label>
          )
        })}
      </fieldset>
      {error && (
        <p role="alert" className="text-rose-300">
          {error}
        </p>
      )}
      <p className="text-2xs text-slate-500">
        Repository locations can't change while backups depend on them; add a
        new store instead.
      </p>
      <BackendTest backend={backend} />
    </div>
  )
}

function ArchiveBackend({ backend }: { backend: StorageBackend }) {
  return (
    <dl>
      <DetailValue
        label="Google Drive folder"
        value={text(backend.config, 'offsite_rclone_remote') ?? 'Not set'}
        mono
      />
    </dl>
  )
}

/** The real backup stores: the restic chain and the older archive folder. */
export function StorageSettings({
  proxmoxConfigured,
}: {
  proxmoxConfigured: boolean
}) {
  const {
    data: backends,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['storage-backends'],
    queryFn: fetchStorageBackends,
  })
  if (isLoading)
    return (
      <p role="status" className="text-xs text-slate-400">
        Loading storage…
      </p>
    )
  if (error)
    return (
      <p role="alert" className="text-xs text-rose-300">
        Storage unavailable: {error.message}
      </p>
    )
  if (!backends?.length)
    return (
      <p className="text-xs text-amber-300">
        No backup storage is set up. Add it with{' '}
        <code className="font-mono">st backup storage</code>.
      </p>
    )
  return (
    <div className="space-y-4 text-xs">
      {backends.map((backend) => {
        const restic = backend.config.engine === 'restic'
        return (
          <section
            key={backend.id}
            aria-label={backend.name}
            className="space-y-2 rounded border border-slate-800/60 bg-slate-950/30 p-3"
          >
            <header className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-sm font-medium text-slate-100">
                {restic ? 'Offsite copies (restic)' : 'Older archives'}
              </h3>
              <span className="text-2xs text-slate-500">
                {backend.name}
                {!backend.enabled && ' · off'}
              </span>
            </header>
            {!restic && (
              <p className="text-slate-400">
                Encrypted archives from before restic, on Google Drive only.
                Nothing expires them; they stay until you remove them.
              </p>
            )}
            {restic ? (
              <ResticBackend
                backend={backend}
                proxmoxConfigured={proxmoxConfigured}
              />
            ) : (
              <ArchiveBackend backend={backend} />
            )}
          </section>
        )
      })}
    </div>
  )
}
