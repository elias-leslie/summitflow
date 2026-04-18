'use client'

import { clsx } from 'clsx'
import {
  CheckCircle2,
  ChevronRight,
  HardDrive,
  Loader2,
  Server,
  Wifi,
  XCircle,
} from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { createStorageBackend, testStorageBackend } from '@/lib/api/backups'

type Step = 'type' | 'details' | 'test' | 'done'

const STEPS: { key: Step; label: string }[] = [
  { key: 'type', label: 'Type' },
  { key: 'details', label: 'Details' },
  { key: 'test', label: 'Test' },
  { key: 'done', label: 'Done' },
]

export function StorageSetupWizard() {
  const router = useRouter()
  const [step, setStep] = useState<Step>('type')
  const [backendType, setBackendType] = useState('smb')
  const [name, setName] = useState('NAS Backup')
  const [host, setHost] = useState('')
  const [share, setShare] = useState('backups')
  const [user, setUser] = useState('backup-svc')
  const [password, setPassword] = useState('')
  const [path, setPath] = useState('project-backups')
  const [isDefault, setIsDefault] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [backendId, setBackendId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{
    success: boolean
    message: string
  } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const currentStepIdx = STEPS.findIndex((s) => s.key === step)

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      const result = await createStorageBackend({
        name,
        backend_type: backendType,
        config: { host, share, user, password, path },
        is_default: isDefault,
      })
      setBackendId(result.id)
      setStep('test')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    if (!backendId) return
    setTesting(true)
    setTestResult(null)
    try {
      const result = await testStorageBackend(backendId)
      setTestResult(result)
      if (result.success) {
        setTimeout(() => setStep('done'), 1000)
      }
    } catch {
      setTestResult({ success: false, message: 'Test request failed' })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="max-w-lg mx-auto">
      {/* Step indicator */}
      <div className="flex items-center gap-2 mb-8">
        {STEPS.map((s, i) => (
          <div key={s.key} className="flex items-center gap-2">
            <div
              className={clsx(
                'w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium border',
                i < currentStepIdx
                  ? 'bg-phosphor-600 border-phosphor-500 text-slate-50'
                  : i === currentStepIdx
                    ? 'bg-phosphor-600/20 border-phosphor-500 text-phosphor-400'
                    : 'bg-slate-800 border-slate-600 text-slate-500',
              )}
            >
              {i < currentStepIdx ? (
                <CheckCircle2 className="w-4 h-4" />
              ) : (
                i + 1
              )}
            </div>
            <span
              className={clsx(
                'text-xs hidden sm:block',
                i === currentStepIdx ? 'text-slate-200' : 'text-slate-500',
              )}
            >
              {s.label}
            </span>
            {i < STEPS.length - 1 && (
              <ChevronRight className="w-4 h-4 text-slate-600" />
            )}
          </div>
        ))}
      </div>

      {/* Step: Type */}
      {step === 'type' && (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-slate-100">
            Where should we store your backups?
          </h2>
          <p className="text-sm text-slate-400">
            Choose a storage type. Most setups use SMB (network share) to send
            backups to a NAS.
          </p>
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => {
                setBackendType('smb')
                setStep('details')
              }}
              className={clsx(
                'w-full p-4 rounded-lg border text-left flex items-center gap-4 transition-colors',
                'bg-slate-800/50 border-slate-700 hover:border-phosphor-500/50',
              )}
            >
              <Server className="w-8 h-8 text-blue-400" />
              <div>
                <p className="text-sm font-medium text-slate-200">
                  Network Share (SMB)
                </p>
                <p className="text-xs text-slate-400">
                  Send backups to your NAS or file server
                </p>
              </div>
            </button>
          </div>
        </div>
      )}

      {/* Step: Details */}
      {step === 'details' && (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-slate-100">
            Enter your connection details
          </h2>
          <p className="text-sm text-slate-400">
            These settings connect to your NAS or file server.
          </p>

          <div className="space-y-3">
            <div>
              <label
                htmlFor="setup-name"
                className="block text-xs text-slate-400 mb-1"
              >
                Name
              </label>
              <input
                id="setup-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-md text-sm text-slate-200
                           focus:outline-none focus:ring-2 focus:ring-phosphor-500"
              />
            </div>
            <div>
              <label
                htmlFor="setup-host"
                className="block text-xs text-slate-400 mb-1"
              >
                Host (IP or hostname)
              </label>
              <input
                id="setup-host"
                type="text"
                value={host}
                onChange={(e) => setHost(e.target.value)}
                placeholder="192.168.1.100 or nas.local"
                className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-md text-sm text-slate-200
                           placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-phosphor-500"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label
                  htmlFor="setup-share"
                  className="block text-xs text-slate-400 mb-1"
                >
                  Share name
                </label>
                <input
                  id="setup-share"
                  type="text"
                  value={share}
                  onChange={(e) => setShare(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-md text-sm text-slate-200
                             focus:outline-none focus:ring-2 focus:ring-phosphor-500"
                />
              </div>
              <div>
                <label
                  htmlFor="setup-path"
                  className="block text-xs text-slate-400 mb-1"
                >
                  Path prefix
                </label>
                <input
                  id="setup-path"
                  type="text"
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-md text-sm text-slate-200
                             focus:outline-none focus:ring-2 focus:ring-phosphor-500"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label
                  htmlFor="setup-user"
                  className="block text-xs text-slate-400 mb-1"
                >
                  Username
                </label>
                <input
                  id="setup-user"
                  type="text"
                  value={user}
                  onChange={(e) => setUser(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-md text-sm text-slate-200
                             focus:outline-none focus:ring-2 focus:ring-phosphor-500"
                />
              </div>
              <div>
                <label
                  htmlFor="setup-password"
                  className="block text-xs text-slate-400 mb-1"
                >
                  Password
                </label>
                <input
                  id="setup-password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-md text-sm text-slate-200
                             focus:outline-none focus:ring-2 focus:ring-phosphor-500"
                />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={isDefault}
                onChange={(e) => setIsDefault(e.target.checked)}
                className="rounded border-slate-500 bg-slate-600 text-phosphor-500 focus:ring-phosphor-500 focus:ring-offset-0"
              />
              Use as default storage backend
            </label>
          </div>

          {error && <p className="text-sm text-rose-400">{error}</p>}

          <div className="flex items-center justify-between pt-2">
            <button
              type="button"
              onClick={() => setStep('type')}
              className="text-sm text-slate-400 hover:text-slate-200 transition-colors"
            >
              Back
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!host || !share || saving}
              className={clsx(
                'flex items-center gap-2 px-4 py-2 text-sm rounded-md font-medium transition-colors',
                host && share && !saving
                  ? 'bg-phosphor-600 text-slate-50 hover:bg-phosphor-500'
                  : 'bg-slate-700 text-slate-400 cursor-not-allowed',
              )}
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
              {saving ? 'Saving...' : 'Save & Test'}
            </button>
          </div>
        </div>
      )}

      {/* Step: Test */}
      {step === 'test' && (
        <div className="space-y-4 text-center">
          <h2 className="text-lg font-semibold text-slate-100">
            Test your connection
          </h2>
          <p className="text-sm text-slate-400">
            Verify that SummitFlow can reach your storage.
          </p>

          {testResult ? (
            <div
              className={clsx(
                'p-4 rounded-lg border',
                testResult.success
                  ? 'bg-green-500/10 border-green-500/30'
                  : 'bg-red-500/10 border-red-500/30',
              )}
            >
              {testResult.success ? (
                <CheckCircle2 className="w-8 h-8 text-green-400 mx-auto mb-2" />
              ) : (
                <XCircle className="w-8 h-8 text-red-400 mx-auto mb-2" />
              )}
              <p
                className={clsx(
                  'text-sm',
                  testResult.success ? 'text-green-400' : 'text-red-400',
                )}
              >
                {testResult.message}
              </p>
            </div>
          ) : (
            <div className="p-8">
              {testing ? (
                <Loader2 className="w-8 h-8 text-phosphor-400 animate-spin mx-auto" />
              ) : (
                <button
                  type="button"
                  onClick={handleTest}
                  className="flex items-center gap-2 mx-auto px-6 py-3 bg-phosphor-600 text-slate-50 rounded-md
                             text-sm font-medium hover:bg-phosphor-500 transition-colors"
                >
                  <Wifi className="w-4 h-4" />
                  Test Connection
                </button>
              )}
            </div>
          )}

          <div className="flex items-center justify-between pt-2">
            <button
              type="button"
              onClick={() => setStep('details')}
              className="text-sm text-slate-400 hover:text-slate-200 transition-colors"
            >
              Back
            </button>
            {testResult && !testResult.success && (
              <button
                type="button"
                onClick={handleTest}
                disabled={testing}
                className="text-sm text-phosphor-400 hover:text-phosphor-300 transition-colors"
              >
                Retry
              </button>
            )}
          </div>
        </div>
      )}

      {/* Step: Done */}
      {step === 'done' && (
        <div className="space-y-4 text-center">
          <CheckCircle2 className="w-12 h-12 text-green-400 mx-auto" />
          <h2 className="text-lg font-semibold text-slate-100">
            Storage configured!
          </h2>
          <p className="text-sm text-slate-400">
            Your backups will now be sent to{' '}
            <strong className="text-slate-300">{name}</strong>. Scheduled
            backups run daily with 14-day retention by default.
          </p>
          <button
            type="button"
            onClick={() => router.push('/backups')}
            className="inline-flex items-center gap-2 px-6 py-2 bg-phosphor-600 text-slate-50 rounded-md
                       text-sm font-medium hover:bg-phosphor-500 transition-colors"
          >
            <HardDrive className="w-4 h-4" />
            Go to Backups
          </button>
        </div>
      )}
    </div>
  )
}
