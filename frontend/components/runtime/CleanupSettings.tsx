'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { type CleanupSetting, runtimeApi } from '@/lib/api/runtime'

const LABELS: Record<string, { label: string; unit: string; hint: string }> = {
  agent_tmp_max_age_hours: {
    label: 'Agent temp folders',
    unit: 'hours',
    hint: 'Session folders in /tmp nothing touched for this long',
  },
  build_tmp_max_age_hours: {
    label: 'Build temp',
    unit: 'hours',
    hint: 'go-build and other build leftovers in /tmp',
  },
  container_max_age_hours: {
    label: 'Stopped containers',
    unit: 'hours',
    hint: 'Docker containers stopped longer than this',
  },
  go_cache_max_gb: {
    label: 'Go build cache',
    unit: 'GB',
    hint: 'Cleared once it grows past this',
  },
}

function SettingRow({
  setting,
  onSave,
  saving,
}: {
  setting: CleanupSetting
  onSave: (name: string, value: number | null) => void
  saving: boolean
}) {
  const meta = LABELS[setting.name] ?? {
    label: setting.name,
    unit: '',
    hint: '',
  }
  const [draft, setDraft] = useState(String(setting.value))
  const parsed = Number(draft)
  const valid =
    draft.trim() !== '' &&
    Number.isFinite(parsed) &&
    parsed >= setting.min &&
    parsed <= setting.max
  const changed = valid && parsed !== setting.value
  const inputId = `cleanup-${setting.name}`

  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-3">
      <label htmlFor={inputId} className="min-w-0 flex-1">
        <span className="block text-xs font-medium text-slate-200">
          {meta.label}
        </span>
        <span className="block text-[11px] text-slate-500">{meta.hint}</span>
      </label>
      <div className="flex items-center gap-2">
        <input
          id={inputId}
          type="number"
          inputMode="decimal"
          min={setting.min}
          max={setting.max}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          aria-invalid={!valid}
          className="w-20 rounded-md border border-slate-700 bg-slate-950/60 px-2 py-1 text-right text-xs text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
        />
        <span className="w-10 text-[11px] text-slate-500">{meta.unit}</span>
        <button
          type="button"
          disabled={!changed || saving}
          onClick={() => onSave(setting.name, parsed)}
          className="rounded-md border border-cyan-500/30 px-2 py-1 text-xs text-cyan-200 hover:bg-cyan-500/10 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
        >
          Save
        </button>
        {setting.saved && (
          <button
            type="button"
            disabled={saving}
            onClick={() => {
              setDraft(String(setting.default))
              onSave(setting.name, null)
            }}
            className="text-[11px] text-slate-400 underline-offset-2 hover:underline disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
          >
            Reset to {setting.default}
          </button>
        )}
      </div>
      {!valid && (
        <span className="text-[11px] text-rose-300 sm:hidden">
          Use {setting.min} to {setting.max}
        </span>
      )}
    </div>
  )
}

export function CleanupSettings() {
  const client = useQueryClient()
  const { data, error, isLoading } = useQuery({
    queryKey: ['runtime', 'cleanup-settings'],
    queryFn: runtimeApi.getCleanupSettings,
  })
  const save = useMutation({
    mutationFn: ({ name, value }: { name: string; value: number | null }) =>
      runtimeApi.saveCleanupSettings({ [name]: value }),
    onSuccess: (next) =>
      client.setQueryData(['runtime', 'cleanup-settings'], next),
  })

  return (
    <section
      aria-labelledby="cleanup-settings-title"
      className="space-y-3 rounded-lg border border-slate-800/80 p-3"
    >
      <div>
        <h3
          id="cleanup-settings-title"
          className="text-sm font-medium text-slate-100"
        >
          Cleanup ages
        </h3>
        <p className="text-[11px] text-slate-500">
          Used by the daily cleanup and the emergency reclaim. Nothing in use is
          removed.
        </p>
      </div>
      {isLoading && (
        <div className="h-16 animate-pulse rounded bg-slate-800/40" />
      )}
      {error && (
        <p className="text-xs text-rose-300">
          {error instanceof Error ? error.message : 'Unavailable'}
        </p>
      )}
      {data?.settings.map((setting) => (
        <SettingRow
          key={`${setting.name}-${setting.value}`}
          setting={setting}
          saving={save.isPending}
          onSave={(name, value) => save.mutate({ name, value })}
        />
      ))}
      {save.error && (
        <p className="text-xs text-rose-300">
          {save.error instanceof Error ? save.error.message : 'Not saved'}
        </p>
      )}
    </section>
  )
}
