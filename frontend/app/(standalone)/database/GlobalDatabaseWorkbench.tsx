'use client'

import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { DatabaseWorkbench } from '@/components/database/DatabaseWorkbench'
import {
  type DbWorkbenchTarget,
  fetchDbWorkbenchTargets,
} from '@/lib/api/db-workbench'

const GLOBAL_TARGET_ID = '__global__'

function preferredTarget(targets: DbWorkbenchTarget[]): string {
  const configured = targets.filter((target) => target.configured)
  return (
    configured.find((target) => target.id === '__db__summitflow')?.id ??
    configured.find((target) => target.id === 'summitflow')?.id ??
    configured.find((target) => target.id !== GLOBAL_TARGET_ID)?.id ??
    configured[0]?.id ??
    GLOBAL_TARGET_ID
  )
}

function targetOptionLabel(target: DbWorkbenchTarget) {
  if (target.shared_with) {
    return `${target.label} (${target.database ?? target.shared_with})`
  }
  return target.database && target.database !== target.label
    ? `${target.label} (${target.database})`
    : target.label
}

export function GlobalDatabaseWorkbench() {
  const [selectedTargetId, setSelectedTargetId] = useState<string | null>(null)

  const targetsQuery = useQuery({
    queryKey: ['db-workbench-targets'],
    queryFn: fetchDbWorkbenchTargets,
    refetchInterval: 30_000,
  })

  const targets = useMemo(
    () => targetsQuery.data?.filter((target) => target.configured) ?? [],
    [targetsQuery.data],
  )

  useEffect(() => {
    if (!targets.length) return
    if (
      selectedTargetId &&
      targets.some((target) => target.id === selectedTargetId)
    ) {
      return
    }
    setSelectedTargetId(preferredTarget(targets))
  }, [selectedTargetId, targets])

  const selectedTarget = selectedTargetId
    ? targets.find((target) => target.id === selectedTargetId)
    : undefined
  const workbenchTargetId = selectedTarget?.id ?? GLOBAL_TARGET_ID

  const targetSelector = (
    <select
      aria-label="Database target"
      value={workbenchTargetId}
      disabled={!targets.length}
      onChange={(event) => setSelectedTargetId(event.target.value)}
      className="h-8 max-w-[44vw] rounded-md border border-slate-700/70 bg-slate-900/80 px-2 text-xs text-slate-200 outline-none transition-colors hover:border-slate-600 focus:border-emerald-500/70 disabled:opacity-50"
    >
      {targets.length ? (
        targets.map((target) => (
          <option key={target.id} value={target.id}>
            {targetOptionLabel(target)}
          </option>
        ))
      ) : (
        <option value={GLOBAL_TARGET_ID}>
          {targetsQuery.isLoading ? 'loading' : 'no databases'}
        </option>
      )}
    </select>
  )

  return (
    <DatabaseWorkbench
      key={workbenchTargetId}
      projectId={workbenchTargetId}
      title="Databases"
      closeHref="/"
      autoStart={Boolean(selectedTarget)}
      stopOnUnmount
      toolbarSlot={targetSelector}
    />
  )
}
