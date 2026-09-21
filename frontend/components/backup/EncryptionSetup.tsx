'use client'

import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import {
  exportBackupRecoveryKey,
  fetchBackupEncryption,
  importBackupRecoveryKey,
  setupBackupEncryption,
  verifyBackupRecoveryKey,
} from '@/lib/api/backups'
import { formatDate } from '@/lib/format'

const actionClass =
  'rounded bg-slate-700 px-3 py-1.5 text-xs text-slate-100 hover:bg-slate-600 disabled:opacity-50'

export function EncryptionSetup() {
  const {
    data: status,
    error: loadError,
    refetch,
  } = useQuery({
    queryKey: ['backup-encryption'],
    queryFn: fetchBackupEncryption,
  })
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [revealedKey, setRevealedKey] = useState<string | null>(null)
  const [savedKey, setSavedKey] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const hide = () => {
      if (document.hidden) setRevealedKey(null)
    }
    document.addEventListener('visibilitychange', hide)
    return () => document.removeEventListener('visibilitychange', hide)
  }, [])

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      await action()
      await refetch()
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : 'The recovery action failed',
      )
    } finally {
      setBusy(false)
    }
  }

  const exportKey = (action: 'download' | 'copy' | 'reveal') =>
    run(async () => {
      const key = await exportBackupRecoveryKey()
      if (action === 'reveal') {
        setRevealedKey(key.recovery_key)
      } else if (action === 'copy') {
        await navigator.clipboard.writeText(key.recovery_key)
        setMessage(
          'Recovery key copied. Save it in your password manager, then verify that saved copy below.',
        )
      } else {
        const url = URL.createObjectURL(
          new Blob([key.recovery_key], { type: 'text/plain' }),
        )
        const link = document.createElement('a')
        link.href = url
        link.download = `summitflow-recovery-${key.key_id.replaceAll(':', '-')}.txt`
        link.click()
        URL.revokeObjectURL(url)
        setMessage(
          'Recovery key downloaded. Save it somewhere you can access if this server is lost, then verify that copy below.',
        )
      }
    })

  const verify = () =>
    run(async () => {
      let recoveryKey = savedKey
      const file = fileInput.current?.files?.[0]
      if (file) recoveryKey = await file.text()
      try {
        if (status?.configured) {
          await verifyBackupRecoveryKey(recoveryKey)
        } else {
          await importBackupRecoveryKey(recoveryKey)
        }
        setRevealedKey(null)
        setMessage(
          'Your saved key decrypted a test message. Recovery-key setup is complete.',
        )
      } finally {
        setSavedKey('')
        if (fileInput.current) fileInput.current.value = ''
      }
    })

  return (
    <section
      aria-label="Backup encryption"
      className="space-y-3 rounded-lg border border-slate-700/60 bg-slate-800/40 p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-200">
          Backup encryption
        </h2>
        <span
          className={
            status?.ready
              ? 'text-xs text-emerald-400'
              : 'text-xs text-amber-400'
          }
        >
          {!status
            ? 'Status unavailable'
            : status.ready
              ? 'Recovery key verified'
              : 'Setup required'}
        </span>
      </div>
      <p className="text-xs text-slate-400">
        New source backups are encrypted locally. Google Drive receives the same
        encrypted archive. Existing backups and system-image encryption are
        tracked separately.
      </p>
      {loadError && (
        <p role="alert" className="text-xs text-red-400">
          Could not load encryption status.{' '}
          <button type="button" className="underline" onClick={() => refetch()}>
            Try again
          </button>
        </p>
      )}
      {status && !status.can_manage_key && (
        <p className="text-xs text-amber-400">
          Open SummitFlow through Cloudflare Access with an owner account to set
          up or retrieve the recovery key.
        </p>
      )}
      {status?.can_manage_key && !status.configured && (
        <button
          type="button"
          className={actionClass}
          disabled={busy}
          onClick={() =>
            run(async () => {
              await setupBackupEncryption()
            })
          }
        >
          Generate recovery key
        </button>
      )}
      {status?.can_manage_key && (
        <details
          open={status.configured && !status.ready}
          onToggle={(event) => {
            if (!event.currentTarget.open) setRevealedKey(null)
          }}
        >
          <summary className="cursor-pointer text-xs font-medium text-slate-300">
            {!status.configured
              ? 'Use an existing recovery key'
              : status.ready
                ? 'Recovery key options'
                : 'Save and verify your recovery key'}
          </summary>
          <div className="mt-3 space-y-3">
            <p className="text-xs text-slate-400">
              Save the key in your password manager. Anyone with this key and a
              backup can decrypt its contents. You can retrieve it here later
              while this server and key remain available.
            </p>
            {status.configured && (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className={actionClass}
                  disabled={busy}
                  onClick={() => exportKey('download')}
                >
                  Download key
                </button>
                <button
                  type="button"
                  className={actionClass}
                  disabled={busy}
                  onClick={() => exportKey('copy')}
                >
                  Copy key
                </button>
                <button
                  type="button"
                  className={actionClass}
                  disabled={busy}
                  onClick={() =>
                    revealedKey ? setRevealedKey(null) : exportKey('reveal')
                  }
                >
                  {revealedKey ? 'Hide key' : 'Reveal key'}
                </button>
              </div>
            )}
            {revealedKey && (
              <pre
                aria-label="Recovery key"
                className="whitespace-pre-wrap break-all rounded bg-slate-950 p-3 text-xs text-slate-200"
              >
                {revealedKey}
              </pre>
            )}
            <div className="space-y-2 border-t border-slate-700 pt-3">
              <label
                className="block text-xs text-slate-300"
                htmlFor="backup-recovery-file"
              >
                Choose the recovery-key file you saved
              </label>
              <input
                ref={fileInput}
                id="backup-recovery-file"
                type="file"
                accept=".txt,.agekey,text/plain"
                className="block w-full text-xs text-slate-400"
                disabled={busy}
              />
              <label
                className="block text-xs text-slate-300"
                htmlFor="backup-recovery-key"
              >
                Or paste the key from your password manager
              </label>
              <textarea
                id="backup-recovery-key"
                value={savedKey}
                onChange={(event) => setSavedKey(event.target.value)}
                autoComplete="off"
                spellCheck={false}
                rows={2}
                disabled={busy}
                className="w-full rounded border border-slate-700 bg-slate-950 p-2 font-mono text-xs text-slate-200"
              />
              <button
                type="button"
                className={actionClass}
                disabled={busy}
                onClick={verify}
              >
                {busy
                  ? 'Working...'
                  : status.configured
                    ? 'Verify saved key'
                    : 'Restore saved key'}
              </button>
              <p className="text-xs text-slate-500">
                This decrypts a small test message with your saved key. It does
                not restore or change project data.
              </p>
            </div>
          </div>
        </details>
      )}
      {status?.key_id && (
        <p className="text-xs text-slate-500">
          Key ID: <span className="font-mono">{status.key_id}</span>
          {status.roundtrip_verified_at &&
            ` · Verified ${formatDate(status.roundtrip_verified_at)}`}
        </p>
      )}
      {status?.protection_limit && (
        <p className="text-xs text-slate-500">{status.protection_limit}</p>
      )}
      {message && (
        <p role="status" className="text-xs text-emerald-400">
          {message}
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-red-400">
          {error}
        </p>
      )}
    </section>
  )
}
