import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  fetchNativeHostBackupStatus,
  type NativeHostBackupStatus,
} from '@/lib/api/backups-infra'
import { NativeHostBackupCard } from './NativeHostBackupCard'

const pending: NativeHostBackupStatus = {
  engine: 'btrbk',
  enabled: false,
  installed: true,
  configured: false,
  ready: false,
  retention: '7 daily destination points; required source incremental parents',
  windows_method: 'Veeam',
  blocked_reason:
    'Native destination and root-owned configuration await storage cutover',
  last_result: null,
}
const ready: NativeHostBackupStatus = {
  ...pending,
  enabled: true,
  configured: true,
  ready: true,
  blocked_reason: null,
  sources: ['/', '/home'],
  target: '/media/backups/native',
  capacity: {
    admitted: true,
    expected_growth_bytes: 1024,
    reserve_bytes: 2048,
    free_bytes: 4096,
    used_bytes: 1024,
    source_filesystems: [
      { path: '/', used_bytes: 512, free_bytes: 4096, under_pressure: false },
    ],
    under_pressure: false,
    reason: null,
  },
  last_result: {
    status: 'completed',
    started_at: '2026-10-05T12:00:00Z',
    finished_at: '2026-10-05T12:15:00Z',
    evidence: '/state/capture.log',
    boot_path: '/media/backups/boot',
    reclaimed_bytes: 0,
    remaining_capacity_bytes: 4096,
  },
}
function openCard() {
  fireEvent.click(screen.getByText('Native Linux Recovery'))
}
afterEach(() => vi.unstubAllGlobals())

describe('Native Linux recovery card', () => {
  it('shows the planned cutover as pending and keeps Windows coverage separate', () => {
    render(
      <NativeHostBackupCard
        status={pending}
        isLoading={false}
        onRefresh={() => {}}
      />,
    )
    expect(screen.getByText('Setup pending')).toBeInTheDocument()
    expect(screen.getByText(pending.blocked_reason ?? '')).toBeInTheDocument()
    openCard()
    expect(screen.getByText('No capture recorded')).toBeVisible()
    expect(
      screen.getByText(
        'Windows recovery uses the Veeam agent in Windows. Linux status does not verify Windows backups.',
      ),
    ).toBeVisible()
    expect(screen.queryByText('Ready to capture')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /start/i }),
    ).not.toBeInTheDocument()
  })

  it('shows actual capacity, latest evidence, boot location and measured zero', () => {
    const refresh = vi.fn()
    render(
      <NativeHostBackupCard
        status={ready}
        isLoading={false}
        onRefresh={refresh}
      />,
    )
    openCard()
    expect(screen.getAllByText('Ready to capture')).toHaveLength(2)
    expect(screen.getByText('Capture headroom available')).toBeVisible()
    expect(screen.getByText('/state/capture.log')).toBeVisible()
    expect(screen.getByText('/media/backups/boot')).toBeVisible()
    expect(screen.getByText('0 B')).toBeVisible()
    fireEvent.click(
      screen.getByRole('button', { name: 'Refresh native Linux status' }),
    )
    expect(refresh).toHaveBeenCalledOnce()
  })

  it('reports pressure and capture failure while preserving evidence access', () => {
    render(
      <NativeHostBackupCard
        status={{
          ...ready,
          ready: false,
          blocked_reason: 'insufficient-host-policy-headroom',
          capacity: ready.capacity && {
            ...ready.capacity,
            admitted: false,
            under_pressure: true,
            reason: 'insufficient-host-policy-headroom',
          },
          last_result: {
            ...ready.last_result,
            status: 'failed',
            error: 'Partial captures retained; inspect journal',
          },
        }}
        isLoading={false}
        onRefresh={() => {}}
      />,
    )
    openCard()
    expect(screen.getAllByText('Blocked')).toHaveLength(2)
    expect(
      screen.getByText(
        'Insufficient capture headroom; destination under pressure',
      ),
    ).toBeVisible()
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Partial captures retained; inspect journal',
    )
    expect(screen.getByText('/state/capture.log')).toBeVisible()
  })

  it('distinguishes failed status loading and preserves the last loaded status', () => {
    const view = render(
      <NativeHostBackupCard
        status={undefined}
        isLoading
        onRefresh={() => {}}
      />,
    )
    openCard()
    expect(screen.getByRole('status')).toHaveTextContent(
      'Loading native host backup status',
    )
    expect(
      screen.getByRole('button', { name: 'Refresh native Linux status' }),
    ).toBeDisabled()
    view.rerender(
      <NativeHostBackupCard
        status={undefined}
        isLoading={false}
        error={new Error('Host unreachable')}
        onRefresh={() => {}}
      />,
    )
    expect(screen.getByText('Unavailable')).toBeVisible()
    expect(screen.getByRole('alert')).toHaveTextContent('Host unreachable')
    view.rerender(
      <NativeHostBackupCard
        status={ready}
        isLoading={false}
        error={new Error('Host unreachable')}
        onRefresh={() => {}}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Refresh failed; showing last loaded status. Host unreachable',
    )
    expect(screen.getByText('/state/capture.log')).toBeVisible()
  })
})

describe('Native Linux status API boundary', () => {
  it('fetches the read-only endpoint and accepts pending and qualified payloads', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(pending)))
      .mockResolvedValueOnce(new Response(JSON.stringify(ready)))
    vi.stubGlobal('fetch', fetch)
    expect(await fetchNativeHostBackupStatus()).toEqual(pending)
    expect(await fetchNativeHostBackupStatus()).toEqual(ready)
    expect(fetch).toHaveBeenCalledWith(
      '/api/backups/native-host',
      expect.objectContaining({
        cache: 'no-store',
        credentials: 'same-origin',
      }),
    )
  })

  it.each([
    { ...pending, ready: 'true' },
    { ...ready, sources: [12] },
    { ...ready, capacity: { ...ready.capacity, free_bytes: -1 } },
    { ...ready, capacity: { ...ready.capacity, source_filesystems: [null] } },
    { ...ready, last_result: { status: 'completed', reclaimed_bytes: '0' } },
  ])('rejects malformed status instead of showing successful protection', async (payload) => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))),
    )
    await expect(fetchNativeHostBackupStatus()).rejects.toThrow(
      'Native Linux backup status is malformed',
    )
  })
})
