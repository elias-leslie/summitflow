import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SourceBackupsClient } from './SourceBackupsClient'

const mockInvalidateQueries = vi.fn().mockResolvedValue(undefined)
const createSourceBackupMock = vi.fn()
const fetchBackupSourceMock = vi.fn()
const fetchSourceBackupsMock = vi.fn()
const fetchStorageSummaryMock = vi.fn()

vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>(
    '@tanstack/react-query',
  )
  return {
    ...actual,
    useQueryClient: () => ({ invalidateQueries: mockInvalidateQueries }),
  }
})

vi.mock('@/lib/api/backups', () => ({
  createSourceBackup: (...args: unknown[]) => createSourceBackupMock(...args),
  fetchBackupSource: (...args: unknown[]) => fetchBackupSourceMock(...args),
  fetchSourceBackups: (...args: unknown[]) => fetchSourceBackupsMock(...args),
  fetchStorageSummary: (...args: unknown[]) => fetchStorageSummaryMock(...args),
  backupHasDatabase: () => false,
}))

function renderClient() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <SourceBackupsClient sourceId="source-1" />
    </QueryClientProvider>,
  )
}

async function submitCreateBackup() {
  renderClient()

  await screen.findByText('Alpha')
  fireEvent.click(screen.getByRole('button', { name: /create backup/i }))
  fireEvent.click(screen.getByRole('button', { name: /^create$/i }))
}

describe('SourceBackupsClient', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchBackupSourceMock.mockResolvedValue({
      id: 'source-1',
      name: 'Alpha',
      path: '/tmp/alpha',
      source_type: 'project',
      project_id: 'project-1',
      enabled: true,
      frequency: 'daily',
      retention_days: 7,
      last_run_at: null,
      next_run_at: null,
      created_at: null,
      updated_at: null,
    })
    fetchSourceBackupsMock.mockResolvedValue({ backups: [], total: 0 })
    fetchStorageSummaryMock.mockResolvedValue({
      total_count: 0,
      total_bytes: 0,
      by_status: {},
    })
  })

  it('shows lost-confirmation warning for ambiguous create errors and refreshes backup state', async () => {
    createSourceBackupMock.mockRejectedValueOnce(new Error('socket hang up'))

    await submitCreateBackup()

    expect(
      await screen.findByText(
        'Queue confirmation was lost while creating backup. It may still be queued. Check Backup History before retrying.',
      ),
    ).toBeInTheDocument()

    await waitFor(() => {
      expect(mockInvalidateQueries).toHaveBeenCalledWith({
        queryKey: ['source-backups', 'source-1'],
      })
      expect(mockInvalidateQueries).toHaveBeenCalledWith({
        queryKey: ['storage-summary', 'source-1'],
      })
    })
  })

  it('keeps real backend create errors as hard failures', async () => {
    createSourceBackupMock.mockRejectedValueOnce(new Error('Source disabled'))

    await submitCreateBackup()

    expect(await screen.findByText('Source disabled')).toBeInTheDocument()
    expect(mockInvalidateQueries).not.toHaveBeenCalled()
  })
})
