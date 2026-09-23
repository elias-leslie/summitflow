import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { useBackupHistoryRefresh } from './backupPolling'

const source = {
  source_id: 'summitflow',
  latest_backup_id: 'old',
  last_success_at: '2026-09-22T12:00:00Z',
  offsite_status: 'verified' as const,
  backup_activity: {
    backup_id: 'old',
    run_id: 'old-run',
    active: false,
    phase: 'complete',
    verified_parts: 0,
  },
}

function setup() {
  const client = new QueryClient()
  const invalidate = vi
    .spyOn(client, 'invalidateQueries')
    .mockResolvedValue(undefined)
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  const hook = renderHook(({ sources }) => useBackupHistoryRefresh(sources), {
    initialProps: { sources: [source] },
    wrapper,
  })
  return { ...hook, invalidate }
}

describe('health-driven backup history refresh', () => {
  it('does not repeat initial reads or refresh for unchanged health polls', () => {
    const { rerender, invalidate } = setup()
    rerender({ sources: [{ ...source }] })
    expect(invalidate).not.toHaveBeenCalled()
  })

  it('refreshes existing history and summary once for an externally started attempt and once when it stops', () => {
    const { rerender, invalidate } = setup()
    const running = {
      ...source,
      backup_activity: {
        ...source.backup_activity,
        backup_id: 'new',
        run_id: 'new-run',
        active: true,
      },
    }
    rerender({ sources: [running] })
    expect(invalidate.mock.calls.map(([filter]) => filter?.queryKey)).toEqual([
      ['all-backups'],
      ['storage-summary'],
    ])
    rerender({ sources: [{ ...running }] })
    expect(invalidate).toHaveBeenCalledTimes(2)
    rerender({
      sources: [
        {
          ...running,
          backup_activity: { ...running.backup_activity, active: false },
        },
      ],
    })
    expect(invalidate).toHaveBeenCalledTimes(4)
  })

  it('detects a short completed attempt between health polls', () => {
    const { rerender, invalidate } = setup()
    rerender({
      sources: [
        {
          ...source,
          latest_backup_id: 'new',
          last_success_at: '2026-09-23T12:00:00Z',
        },
      ],
    })
    expect(invalidate).toHaveBeenCalledTimes(2)
  })

  it('does not invalidate for changing phase or part evidence within the same attempt', () => {
    const { rerender, invalidate } = setup()
    const activity = {
      ...source.backup_activity,
      phase: 'upload',
      verified_parts: 1,
    }
    rerender({ sources: [{ ...source, backup_activity: activity }] })
    rerender({
      sources: [
        {
          ...source,
          backup_activity: {
            ...activity,
            phase: 'verification',
            verified_parts: 2,
          },
        },
      ],
    })
    expect(invalidate).not.toHaveBeenCalled()
  })
})
