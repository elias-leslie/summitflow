import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  BtrfsScope,
  BtrfsSnapshot,
  BtrfsSummary,
} from '@/lib/api/snapshots'
import { ProjectSnapshotsCard } from './ProjectSnapshotsCard'
import { SavedWorkEvidence } from './SavedWorkEvidence'
import { ScopeList } from './ScopeList'
import { SnapshotRow } from './SnapshotRow'

const api = vi.hoisted(() => ({
  fetchSnapshots: vi.fn(),
  recoverSnapshot: vi.fn(),
  releaseSnapshotRecovery: vi.fn(),
  previewSnapshotRecovery: vi.fn(),
  createSnapshot: vi.fn(),
  pruneSnapshots: vi.fn(),
  fetchSnapshotSummary: vi.fn(),
  fetchScopes: vi.fn(),
}))
vi.mock('@/lib/api/snapshots', () => api)

const snapshot: BtrfsSnapshot = {
  id: 'snap-1',
  name: 'saved edits',
  project_id: 'alpha',
  scope_type: 'project',
  scope_name: 'alpha',
  branch: 'main',
  head_oid: null,
  created_at: '2026-10-05T12:00:00Z',
  source: 'auto-periodic',
  usage: null,
}
const scope: BtrfsScope = {
  project_id: 'alpha',
  scope_type: 'project',
  scope_name: 'alpha',
  scope_state: 'active',
  snapshot_count: 1,
  total_bytes: null,
  newest_at: snapshot.created_at,
  oldest_at: snapshot.created_at,
}
const summary: BtrfsSummary = {
  total_snapshots: 1,
  total_usage_bytes: null,
  by_source: { 'auto-periodic': 1 },
  by_scope_type: { project: 1 },
  scope_count: 1,
  active_snapshot_count: 1,
  archived_snapshot_count: 0,
  active_scope_count: 1,
  archived_scope_count: 0,
  autosnap_timer_active: true,
  policy: {
    interval_minutes: 5,
    baseline_stale_minutes: 15,
    recent_hours: 6,
    hourly_hours: 24,
    daily_days: 3,
    archived_keep_days: 14,
    pressure_keep_points: 3,
    manual_keep_per_scope: 8,
    max_deletes_per_run: 15,
    delete_batch: 5,
  },
}

function renderQuery(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const view = render(
    <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  )
  return { ...view, client, invalidate }
}

beforeEach(() => {
  vi.resetAllMocks()
  api.fetchSnapshots.mockResolvedValue([snapshot])
})

describe('Saved-work recovery', () => {
  it('retains the actual read-only path and releases only recovery protection', async () => {
    api.recoverSnapshot.mockResolvedValue({
      ok: true,
      recovery_path: '/recovery/alpha',
    })
    api.releaseSnapshotRecovery.mockResolvedValue({
      ok: true,
      recovery_active: false,
      recovery_path: '/recovery/alpha',
    })
    const { invalidate } = renderQuery(<SnapshotRow snap={snapshot} />)
    expect(screen.getByText('Size unavailable')).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Open read-only side copy of saved edits',
      }),
    )
    expect(await screen.findByText('/recovery/alpha')).toBeInTheDocument()
    expect(api.recoverSnapshot).toHaveBeenCalledWith('snap-1', 'alpha')
    fireEvent.click(
      screen.getByRole('button', { name: 'Release recovery protection' }),
    )
    expect(
      await screen.findByText(
        'Protection released; side copy will be removed by pruning',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('/recovery/alpha')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Release recovery protection' }),
    ).not.toBeInTheDocument()
    expect(api.releaseSnapshotRecovery).toHaveBeenCalledWith('snap-1', 'alpha')
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['snapshot-scope'] })
  })

  it('shows recovery and release failures and preserves the active pin', async () => {
    api.recoverSnapshot.mockResolvedValue({
      ok: false,
      error: 'Capture inaccessible',
    })
    api.releaseSnapshotRecovery.mockRejectedValue(new Error('Release denied'))
    renderQuery(
      <SnapshotRow
        snap={{
          ...snapshot,
          recovery_path: '/recovery/alpha',
          recovery_active: true,
          deletion_error: 'Subvolume busy',
        }}
      />,
    )
    expect(screen.getByText('Prune failed: Subvolume busy')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /open read-only/i }))
    expect(await screen.findByText('Capture inaccessible')).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', { name: 'Release recovery protection' }),
    )
    expect(await screen.findByText('Release denied')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Release recovery protection' }),
    ).toBeEnabled()
  })

  it('compares selected paths and reports the backend apply limit without an apply control', async () => {
    api.previewSnapshotRecovery.mockResolvedValue({
      ok: true,
      snapshot_id: 'snap-1',
      project_id: 'alpha',
      scope_path: '/projects/alpha',
      files: [
        { path: 'src/app.ts', current_digest: 'abc', captured_digest: 'def' },
      ],
      preview_digest: 'preview-1',
      apply_available: false,
      apply_reason:
        'Apply through an ST coding session with an active own lease',
    })
    renderQuery(<SnapshotRow snap={snapshot} />)
    fireEvent.click(screen.getByText('Preview selected files'))
    expect(
      screen.getByRole('button', { name: 'Compare selected files' }),
    ).toBeDisabled()
    fireEvent.change(
      screen.getByLabelText('Project-relative paths, one per line'),
      { target: { value: ' src/app.ts\n\n' } },
    )
    fireEvent.click(
      screen.getByRole('button', { name: 'Compare selected files' }),
    )
    expect(
      await screen.findByText('Differs from captured file'),
    ).toBeInTheDocument()
    expect(api.previewSnapshotRecovery).toHaveBeenCalledWith(
      'snap-1',
      'alpha',
      ['src/app.ts'],
    )
    expect(
      screen.getByText(
        'Apply through an ST coding session with an active own lease',
      ),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /apply/i }),
    ).not.toBeInTheDocument()
    fireEvent.change(
      screen.getByLabelText('Project-relative paths, one per line'),
      { target: { value: 'src/other.ts' } },
    )
    expect(
      screen.queryByText('Differs from captured file'),
    ).not.toBeInTheDocument()
  })

  it('keeps scope fetch errors distinct from empty results and supports retry', async () => {
    api.fetchSnapshots
      .mockRejectedValueOnce(new Error('Snapshot store unavailable'))
      .mockResolvedValue([])
    renderQuery(<ScopeList scopes={[scope]} />)
    const toggle = screen.getByRole('button', { name: /project active alpha/i })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(toggle)
    expect(
      await screen.findByText(
        'Snapshots unavailable: Snapshot store unavailable',
      ),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('No snapshots in this scope'),
    ).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry snapshots' }))
    expect(
      await screen.findByText('No snapshots in this scope'),
    ).toBeInTheDocument()
    fireEvent.click(toggle)
    expect(screen.getByText('No snapshots in this scope')).not.toBeVisible()
  })

  it('shows saved-work captures separately from offsite evidence in Development', async () => {
    renderQuery(<SavedWorkEvidence projectId="alpha" />)
    expect(screen.getByText('Loading Btrfs captures…')).toBeInTheDocument()
    expect(
      await screen.findByText('1 Btrfs saved-work snapshot'),
    ).toBeInTheDocument()
    expect(api.fetchSnapshots).toHaveBeenCalledWith('alpha')
    expect(
      screen.getByRole('link', { name: 'Inspect saved-work recovery' }),
    ).toHaveAttribute('href', '/backups')
    expect(api.recoverSnapshot).not.toHaveBeenCalled()
  })

  it('keeps loaded recovery controls available when a refresh fails', async () => {
    const { client } = renderQuery(<ScopeList scopes={[scope]} />)
    fireEvent.click(
      screen.getByRole('button', { name: /project active alpha/i }),
    )
    expect(
      await screen.findByRole('button', { name: /open read-only/i }),
    ).toBeEnabled()
    api.fetchSnapshots.mockRejectedValue(new Error('Store unavailable'))
    await act(() => client.invalidateQueries({ queryKey: ['snapshot-scope'] }))
    expect(
      await screen.findByText(
        'Refresh failed; showing last loaded snapshots: Store unavailable',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /open read-only/i }),
    ).toBeEnabled()
  })

  it('identifies missing files instead of calling absent digests a content match', async () => {
    api.previewSnapshotRecovery.mockResolvedValue({
      ok: true,
      files: [
        {
          path: 'missing.ts',
          current_digest: 'missing',
          captured_digest: 'missing',
        },
      ],
      apply_available: false,
      apply_reason: 'Apply requires an owned ST coding session',
    })
    renderQuery(<SnapshotRow snap={snapshot} />)
    fireEvent.click(screen.getByText('Preview selected files'))
    fireEvent.change(
      screen.getByLabelText('Project-relative paths, one per line'),
      { target: { value: 'missing.ts' } },
    )
    fireEvent.click(
      screen.getByRole('button', { name: 'Compare selected files' }),
    )
    expect(
      await screen.findByText('File absent from workspace and snapshot'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Matches captured file')).not.toBeInTheDocument()
  })
})

describe('Project snapshots card', () => {
  beforeEach(() => {
    api.fetchSnapshotSummary.mockResolvedValue(summary)
    api.fetchScopes.mockResolvedValue([scope])
    api.fetchSnapshots.mockResolvedValue([snapshot])
  })

  function openDetails() {
    fireEvent.click(screen.getByText('Space used and retention'))
  }

  it('keeps unknown size apart from zero and states the retention policy', async () => {
    const view = renderQuery(<ProjectSnapshotsCard />)
    await screen.findByText('Every 5 min')
    openDetails()
    expect(screen.getByText('Not measured')).toBeInTheDocument()
    expect(
      screen.getByText(
        /Keeps every snapshot for 6 h, one an hour to 24 h, then one a day for 3 days\. Retired projects keep their newest snapshot for 14 days\. When the disk is low, only the newest 3 are kept\./,
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('Every 5 min')).toBeInTheDocument()
    view.unmount()

    api.fetchSnapshotSummary.mockResolvedValue({
      ...summary,
      total_usage_bytes: 0,
    })
    renderQuery(<ProjectSnapshotsCard />)
    await screen.findByText('Every 5 min')
    openDetails()
    expect(screen.getByText('0 B')).toBeInTheDocument()
  })

  it('reports a partial prune failure and refreshes snapshot status', async () => {
    api.pruneSnapshots.mockResolvedValue({
      ok: false,
      pruned: 2,
      error: 'Pinned capture skipped',
    })
    const { invalidate } = renderQuery(<ProjectSnapshotsCard />)
    await screen.findByText('Every 5 min')
    fireEvent.click(screen.getByRole('button', { name: 'Prune now' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '2 pruned; Pinned capture skipped',
    )
    expect(api.pruneSnapshots).toHaveBeenCalledWith(false)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['snapshot-summary'] })
  })

  it('handles failed prune payloads without a deletion count', async () => {
    api.pruneSnapshots.mockResolvedValue({
      ok: false,
      error: 'Storage unavailable',
    })
    renderQuery(<ProjectSnapshotsCard />)
    await screen.findByText('Every 5 min')
    fireEvent.click(screen.getByRole('button', { name: 'Prune now' }))
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Storage unavailable',
      ),
    )
    expect(screen.queryByText(/undefined/)).not.toBeInTheDocument()
  })

  it('shows loading, then the failure, instead of hiding the card', async () => {
    let fail: (error: Error) => void = () => {}
    api.fetchSnapshotSummary.mockReturnValue(
      new Promise((_, reject) => {
        fail = reject
      }),
    )
    renderQuery(<ProjectSnapshotsCard />)
    expect(screen.getByText('Loading…')).toHaveAttribute('role', 'status')
    act(() => fail(new Error('Offline')))
    expect(await screen.findByRole('alert')).toHaveTextContent('Offline')
    expect(screen.getByText('Status unavailable')).toBeInTheDocument()
  })
})
