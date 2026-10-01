import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  controlManagedCodex,
  fetchManagedCodexStatus,
  managedEvidenceUrl,
  parseManagedCodexStatus,
} from '@/lib/api/managed-codex'
import { ManagedCodexCapture } from './ManagedCodexCapture'

vi.mock('@/lib/api/managed-codex', async (original) => ({
  ...(await original<typeof import('@/lib/api/managed-codex')>()),
  controlManagedCodex: vi.fn(),
  fetchManagedCodexStatus: vi.fn(),
}))

const status = parseManagedCodexStatus({
  available: true,
  project_id: 'agent-hub',
  installed_version: 'codex-cli 0.159.3',
  installed_protocol_status: 'compatible',
  capture_enabled: true,
  capture_disabled: false,
  health: 'initialized',
  delivery_health: 'pending',
  capture_gaps: 0,
  pending: 2,
  pending_bytes: 500,
  quarantined: 1,
  quarantined_bytes: 20,
  used_bytes: 520,
  quota_bytes: 10000,
  raw_retention_seconds: 3600,
  physical_bytes: 1000,
  process_active: true,
  actions: ['disable', 'drain'],
  threads: [
    {
      thread_id: 'thread',
      project_id: 'agent-hub',
      source_id: 'source',
      acknowledged: 0,
      provider_version: '0.159.2',
      schema_fingerprint: 'fingerprint',
      generation: 0,
    },
  ],
  promotion_state: 'shadow',
  agent_hub_url: 'https://hub.example.test',
})

function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ManagedCodexCapture />
    </QueryClientProvider>,
  )
}
afterEach(() => {
  vi.resetAllMocks()
  vi.restoreAllMocks()
})

describe('managed Codex runtime controls', () => {
  it('keeps project choices while loading and binds controls to the selected project', async () => {
    let resolveSelected: ((value: typeof status) => void) | undefined
    vi.mocked(fetchManagedCodexStatus)
      .mockResolvedValueOnce({
        ...status,
        configured_projects: ['agent-hub', 'summitflow'],
      })
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSelected = resolve
          }),
      )
    vi.mocked(controlManagedCodex).mockResolvedValue({
      ...status,
      project_id: 'summitflow',
      configured_projects: ['agent-hub', 'summitflow'],
      threads: [],
      actions: ['enable'],
    })
    mount()
    const selector = await screen.findByRole('combobox', { name: 'Project' })
    expect(selector).toHaveValue('agent-hub')
    fireEvent.change(selector, { target: { value: 'summitflow' } })
    await waitFor(() =>
      expect(fetchManagedCodexStatus).toHaveBeenLastCalledWith('summitflow'),
    )
    expect(screen.getByRole('combobox', { name: 'Project' })).toHaveValue(
      'summitflow',
    )
    expect(
      screen.getByText('Checking runtime compatibility...'),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Disable capture' }),
    ).not.toBeInTheDocument()
    resolveSelected?.({
      ...status,
      project_id: 'summitflow',
      configured_projects: ['agent-hub', 'summitflow'],
      threads: [],
    })
    const disable = await screen.findByRole('button', {
      name: 'Disable capture',
    })
    await waitFor(() => expect(disable).toBeEnabled())
    fireEvent.click(disable)
    await waitFor(() =>
      expect(controlManagedCodex).toHaveBeenCalledWith('summitflow', 'disable'),
    )
    expect(
      await screen.findByRole('button', { name: 'Re-enable capture' }),
    ).toBeInTheDocument()
  })

  it('keeps the selector available to recover from a selected project failure', async () => {
    vi.mocked(fetchManagedCodexStatus)
      .mockResolvedValueOnce({
        ...status,
        configured_projects: ['agent-hub', 'summitflow'],
      })
      .mockRejectedValueOnce(new Error('503'))
      .mockResolvedValueOnce({
        ...status,
        configured_projects: ['agent-hub', 'summitflow'],
      })
    mount()
    const selector = await screen.findByRole('combobox', { name: 'Project' })
    fireEvent.change(selector, { target: { value: 'summitflow' } })
    expect(
      await screen.findByText(/Owner access or capture status is unavailable/),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Disable capture' }),
    ).not.toBeInTheDocument()
    fireEvent.change(selector, { target: { value: 'agent-hub' } })
    expect(
      await screen.findByRole('button', { name: 'Disable capture' }),
    ).toBeInTheDocument()
    expect(fetchManagedCodexStatus).toHaveBeenLastCalledWith('agent-hub')
  })

  it('omits the selector for one configured project', async () => {
    vi.mocked(fetchManagedCodexStatus).mockResolvedValue({
      ...status,
      configured_projects: ['agent-hub'],
    })
    mount()
    await screen.findByText(/Installed codex-cli/)
    expect(
      screen.queryByRole('combobox', { name: 'Project' }),
    ).not.toBeInTheDocument()
  })

  it('requests the exact project on the authenticated same-origin API and rejects mismatched bindings', async () => {
    const api = await vi.importActual<typeof import('@/lib/api/managed-codex')>(
      '@/lib/api/managed-codex',
    )
    const fetch = vi.spyOn(globalThis, 'fetch')
    const selected = { ...status, project_id: 'summitflow', threads: [] }
    fetch.mockResolvedValueOnce(new Response(JSON.stringify(selected)))
    await api.fetchManagedCodexStatus('summitflow')
    expect(fetch).toHaveBeenLastCalledWith(
      '/api/projects/managed-codex?project_id=summitflow',
      expect.objectContaining({
        credentials: 'same-origin',
        cache: 'no-store',
      }),
    )
    fetch.mockResolvedValueOnce(new Response(JSON.stringify(selected)))
    await api.controlManagedCodex('summitflow', 'drain')
    expect(fetch).toHaveBeenLastCalledWith(
      '/api/projects/summitflow/managed-codex/drain',
      expect.objectContaining({ credentials: 'same-origin', method: 'POST' }),
    )
    fetch.mockResolvedValueOnce(new Response(JSON.stringify(status)))
    await expect(api.fetchManagedCodexStatus('summitflow')).rejects.toThrow(
      'binding mismatch',
    )
    fetch.mockResolvedValueOnce(new Response(JSON.stringify(status)))
    await expect(
      api.controlManagedCodex('summitflow', 'drain'),
    ).rejects.toThrow('binding mismatch')
    expect(() =>
      parseManagedCodexStatus({
        ...status,
        configured_projects: [{ path: '/tmp' }],
      }),
    ).toThrow('incompatible')
  })

  it('performs each explicitly selected update stage using backend capabilities', async () => {
    const update = {
      state: 'unchecked' as const,
      latest_version: null,
      candidate_version: null,
      active_version: null,
      previous_version: null,
      error_code: null,
    }
    vi.mocked(fetchManagedCodexStatus).mockResolvedValue({
      ...status,
      actions: ['check-update'],
      update,
    })
    vi.mocked(controlManagedCodex)
      .mockResolvedValueOnce({
        ...status,
        actions: ['stage-update'],
        update: { ...update, state: 'available', latest_version: '0.159.4' },
      })
      .mockResolvedValueOnce({
        ...status,
        actions: ['qualify-update'],
        update: {
          ...update,
          state: 'staged',
          latest_version: '0.159.4',
          candidate_version: '0.159.4',
        },
      })
      .mockResolvedValueOnce({
        ...status,
        actions: ['promote-update'],
        update: {
          ...update,
          state: 'qualified',
          latest_version: '0.159.4',
          candidate_version: '0.159.4',
        },
      })
      .mockResolvedValueOnce({
        ...status,
        actions: ['rollback-update'],
        update: {
          ...update,
          state: 'active',
          latest_version: '0.159.4',
          candidate_version: '0.159.4',
          active_version: '0.159.4',
          previous_version: '0.159.3',
        },
      })
      .mockResolvedValueOnce({
        ...status,
        actions: ['check-update'],
        update: {
          ...update,
          state: 'rolled_back',
          active_version: '0.159.3',
          previous_version: '0.159.4',
        },
      })
    mount()
    expect(
      screen.queryByRole('button', { name: 'Stage update (install)' }),
    ).not.toBeInTheDocument()
    for (const [label, kind] of [
      ['Check for Codex update', 'check-update'],
      ['Stage update (install)', 'stage-update'],
      ['Qualify staged runtime', 'qualify-update'],
      ['Promote staged runtime', 'promote-update'],
      ['Rollback runtime', 'rollback-update'],
    ]) {
      const button = await screen.findByRole('button', { name: label })
      await waitFor(() => expect(button).toBeEnabled())
      fireEvent.click(button)
      await waitFor(() =>
        expect(controlManagedCodex).toHaveBeenLastCalledWith('agent-hub', kind),
      )
    }
    expect(
      await screen.findByText(/Previous runtime restored for future launches/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/running sessions keep their pinned/),
    ).toBeInTheDocument()
  })

  it('rejects update controls without an accompanying verified status shape', () => {
    expect(() =>
      parseManagedCodexStatus({ ...status, actions: ['stage-update'] }),
    ).toThrow('unavailable')
    expect(() =>
      parseManagedCodexStatus({ ...status, update: { state: 'pretend' } }),
    ).toThrow('incompatible')
  })
  it('separates installed compatibility from recorded session versions and binds the real control', async () => {
    vi.mocked(fetchManagedCodexStatus).mockResolvedValue(status)
    vi.mocked(controlManagedCodex).mockResolvedValue({
      ...status,
      capture_disabled: true,
      health: 'disabled',
      actions: ['enable', 'drain'],
    })
    mount()
    expect(
      await screen.findByText(/Installed codex-cli 0.159.3/),
    ).toBeInTheDocument()
    expect(screen.getByText('Session runtime 0.159.2')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Agent Hub evidence' }),
    ).toHaveAttribute(
      'href',
      'https://hub.example.test/sessions/thread?tab=info',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Disable capture' }))
    expect(
      await screen.findByRole('button', { name: 'Re-enable capture' }),
    ).toBeInTheDocument()
    expect(controlManagedCodex).toHaveBeenCalledWith('agent-hub', 'disable')
    expect(
      screen.getByText(/do not decide approvals or replay model work/),
    ).toBeInTheDocument()
  })

  it('shows unavailable health without creating controls or reporting absent counters as zero', async () => {
    vi.mocked(fetchManagedCodexStatus).mockResolvedValue({
      ...status,
      available: false,
      project_id: null,
      actions: [],
      threads: [],
    })
    mount()
    expect(
      await screen.findByText(/Managed owner unavailable/),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Disable capture' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText('Pending / quarantined records'),
    ).not.toBeInTheDocument()
  })

  it('supports status recovery after owner access fails', async () => {
    vi.mocked(fetchManagedCodexStatus)
      .mockRejectedValueOnce(new Error('403'))
      .mockResolvedValueOnce(status)
    mount()
    expect(
      await screen.findByText(/Owner access or capture status is unavailable/),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh status' }))
    expect(
      await screen.findByText(/Installed codex-cli 0.159.3/),
    ).toBeInTheDocument()
  })

  it('rejects incompatible data and unsafe evidence destinations', () => {
    expect(() => parseManagedCodexStatus({ ...status, pending: -1 })).toThrow(
      'incompatible',
    )
    expect(managedEvidenceUrl('javascript:alert(1)', 'thread')).toBeNull()
    const parsed = parseManagedCodexStatus({ ...status, raw_payload: 'secret' })
    expect(JSON.stringify(parsed)).not.toContain('secret')
  })
})
