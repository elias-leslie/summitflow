'use client'

import { useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { Loader2, RotateCcw } from 'lucide-react'
import { useId, useState } from 'react'
import {
  type BtrfsSnapshot,
  previewSnapshotRecovery,
  recoverSnapshot,
  releaseSnapshotRecovery,
  type SelectedRecoveryPreview,
} from '@/lib/api/snapshots'
import { formatBytes, formatTimeAgo } from '@/lib/format'

const SOURCE_DOT: Record<string, string> = {
  manual: 'bg-phosphor-500',
  'auto-baseline': 'bg-emerald-500',
  'auto-periodic': 'bg-slate-500',
  'auto-claim': 'bg-amber-500',
}

const SOURCE_BADGE: Record<string, string> = {
  manual: 'bg-phosphor-500/12 text-phosphor-400 border-phosphor-500/20',
  'auto-baseline': 'bg-emerald-500/12 text-emerald-400 border-emerald-500/20',
  'auto-periodic': 'bg-slate-700/50 text-slate-400 border-slate-600/40',
  'auto-claim': 'bg-amber-500/12 text-amber-400 border-amber-500/20',
}

const SOURCE_LABEL: Record<string, string> = {
  manual: 'manual',
  'auto-baseline': 'baseline',
  'auto-periodic': 'periodic',
  'auto-claim': 'claim',
}

const controlClass =
  'rounded px-2 py-1 text-xs text-slate-300 hover:bg-slate-700/60 disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400'

export function SnapshotRow({ snap }: { snap: BtrfsSnapshot }) {
  const queryClient = useQueryClient()
  const pathsId = useId()
  const [busy, setBusy] = useState<'recover' | 'release' | 'preview' | null>(
    null,
  )
  const [feedback, setFeedback] = useState<{
    ok: boolean
    message: string
  } | null>(null)
  const [recovery, setRecovery] = useState<{
    path: string | null
    active: boolean
  } | null>(null)
  const [paths, setPaths] = useState('')
  const [preview, setPreview] = useState<SelectedRecoveryPreview | null>(null)
  const recoveryPath = recovery ? recovery.path : snap.recovery_path
  const recoveryActive = recovery ? recovery.active : snap.recovery_active
  const displayName = snap.name ?? snap.id.slice(0, 20)

  const refresh = () => {
    for (const key of [
      'snapshot-scope',
      'snapshot-summary',
      'snapshot-scopes',
      'saved-work-evidence',
    ]) {
      queryClient.invalidateQueries({ queryKey: [key] })
    }
  }

  const handleRecover = async () => {
    setBusy('recover')
    setFeedback(null)
    try {
      const result = await recoverSnapshot(snap.id, snap.project_id)
      if (result.ok) {
        setRecovery({ path: result.recovery_path ?? null, active: true })
        setFeedback({
          ok: true,
          message: result.recovery_path
            ? 'Read-only side copy opened'
            : 'Side copy opened; recovery location unavailable',
        })
        refresh()
      } else {
        setFeedback({ ok: false, message: result.error ?? 'Recovery failed' })
      }
    } catch (error) {
      setFeedback({
        ok: false,
        message: error instanceof Error ? error.message : 'Recovery failed',
      })
    } finally {
      setBusy(null)
    }
  }

  const handleRelease = async () => {
    setBusy('release')
    setFeedback(null)
    try {
      const result = await releaseSnapshotRecovery(snap.id, snap.project_id)
      if (result.ok) {
        setRecovery({
          path: result.recovery_path ?? recoveryPath ?? null,
          active: result.recovery_active ?? false,
        })
        setFeedback({
          ok: true,
          message: 'Protection released; side copy will be removed by pruning',
        })
        refresh()
      } else {
        setFeedback({ ok: false, message: result.error ?? 'Release failed' })
      }
    } catch (error) {
      setFeedback({
        ok: false,
        message: error instanceof Error ? error.message : 'Release failed',
      })
    } finally {
      setBusy(null)
    }
  }

  const handlePreview = async () => {
    setBusy('preview')
    setPreview(null)
    try {
      setPreview(
        await previewSnapshotRecovery(
          snap.id,
          snap.project_id,
          paths
            .split('\n')
            .map((path) => path.trim())
            .filter(Boolean),
        ),
      )
    } catch (error) {
      setPreview({
        ok: false,
        error: error instanceof Error ? error.message : 'Preview failed',
      })
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="rounded border border-slate-800/40 bg-slate-950/40 px-2.5 py-2 text-xs space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <div
          className={clsx(
            'w-1.5 h-1.5 rounded-full shrink-0',
            SOURCE_DOT[snap.source] ?? 'bg-slate-600',
          )}
        />
        <span
          className={clsx(
            'inline-flex items-center px-1.5 py-0.5 rounded text-[9px] uppercase tracking-[0.1em] font-medium border leading-none shrink-0',
            SOURCE_BADGE[snap.source] ?? SOURCE_BADGE['auto-periodic'],
          )}
        >
          {SOURCE_LABEL[snap.source] ?? snap.source}
        </span>
        <span className="min-w-0 break-all text-slate-200" title={snap.id}>
          {displayName}
        </span>
        {snap.branch && (
          <span className="min-w-0 break-all font-mono text-slate-400">
            {snap.branch}
          </span>
        )}
        <span className="ml-auto text-slate-400">
          {formatTimeAgo(snap.created_at)}
        </span>
        <span className="font-mono text-slate-400">
          {snap.usage
            ? snap.usage.exclusive_bytes === 0
              ? '0 B'
              : formatBytes(snap.usage.exclusive_bytes)
            : 'Size unavailable'}
        </span>
        <button
          type="button"
          onClick={handleRecover}
          disabled={busy !== null}
          className={clsx(controlClass, 'flex items-center gap-1')}
          aria-label={`Open read-only side copy of ${displayName}`}
        >
          {busy === 'recover' ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <RotateCcw className="h-3 w-3" />
          )}
          Open side copy
        </button>
      </div>
      {recoveryPath && (
        <div className="space-y-1">
          <div className="text-slate-400">Read-only recovery location</div>
          <code className="block break-all text-slate-200">{recoveryPath}</code>
        </div>
      )}
      {snap.recovery_cleanup_pending && (
        <p className="text-xs text-slate-400">Side copy awaits pruning</p>
      )}
      {snap.recovery_deletion_error && (
        <p role="alert" className="break-words text-rose-300">
          Side-copy cleanup failed: {snap.recovery_deletion_error}
        </p>
      )}
      {recoveryActive && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-amber-300">
            Recovery protection active
            {snap.pin_reason ? `: ${snap.pin_reason}` : ''}
          </span>
          <button
            type="button"
            onClick={handleRelease}
            disabled={busy !== null}
            className={controlClass}
          >
            {busy === 'release' ? 'Releasing…' : 'Release recovery protection'}
          </button>
        </div>
      )}
      {snap.deletion_error && (
        <p role="alert" className="break-words text-rose-300">
          Prune failed: {snap.deletion_error}
        </p>
      )}
      {feedback && (
        <p
          role={feedback.ok ? 'status' : 'alert'}
          className={feedback.ok ? 'text-emerald-300' : 'text-rose-300'}
        >
          {feedback.message}
        </p>
      )}
      <details>
        <summary className="cursor-pointer text-slate-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400">
          Preview selected files
        </summary>
        <form
          className="mt-2 space-y-2"
          onSubmit={(event) => {
            event.preventDefault()
            void handlePreview()
          }}
        >
          <label htmlFor={pathsId} className="block text-slate-400">
            Project-relative paths, one per line
          </label>
          <textarea
            id={pathsId}
            value={paths}
            onChange={(event) => {
              setPaths(event.target.value)
              setPreview(null)
            }}
            rows={2}
            required
            disabled={busy !== null}
            className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-slate-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
          />
          <button
            type="submit"
            disabled={busy !== null || !paths.trim()}
            className={controlClass}
          >
            {busy === 'preview' ? 'Comparing…' : 'Compare selected files'}
          </button>
        </form>
        {preview &&
          (preview.ok ? (
            <div className="mt-2 space-y-2">
              <ul className="space-y-2">
                {preview.files.map((file) => (
                  <li
                    key={file.path}
                    className="min-w-0 space-y-1 text-slate-300"
                  >
                    <div className="break-all font-mono">{file.path}</div>
                    <div>
                      {file.current_digest === 'missing'
                        ? file.captured_digest === 'missing'
                          ? 'File absent from workspace and snapshot'
                          : 'File missing from current workspace'
                        : file.captured_digest === 'missing'
                          ? 'File missing from snapshot'
                          : file.current_digest === file.captured_digest
                            ? 'Matches captured file'
                            : 'Differs from captured file'}
                    </div>
                    <details>
                      <summary className="cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400">
                        Content digests
                      </summary>
                      <dl className="mt-1 space-y-1 break-all font-mono">
                        <dt className="text-slate-400">Current</dt>
                        <dd>{file.current_digest}</dd>
                        <dt className="text-slate-400">Captured</dt>
                        <dd>{file.captured_digest}</dd>
                      </dl>
                    </details>
                  </li>
                ))}
              </ul>
              <p role="status" className="break-words text-amber-300">
                {preview.apply_reason}
              </p>
            </div>
          ) : (
            <p role="alert" className="mt-2 text-rose-300">
              {preview.error}
            </p>
          ))}
      </details>
    </div>
  )
}
