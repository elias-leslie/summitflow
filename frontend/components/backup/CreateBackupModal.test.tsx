import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { type BackupSource, createSourceBackup } from '@/lib/api/backups'
import { CreateBackupModal } from './CreateBackupModal'

vi.mock('@/lib/api/backups', () => ({
  createSourceBackup: vi.fn(),
}))

const createSourceBackupMock = vi.mocked(createSourceBackup)

const sources: BackupSource[] = [
  {
    id: 'alpha',
    name: 'Alpha',
    path: '/tmp/alpha',
    source_type: 'project',
    project_id: 'alpha',
    enabled: true,
    frequency: 'daily',
    retention_days: 7,
    last_run_at: null,
    next_run_at: null,
    created_at: null,
    updated_at: null,
  },
  {
    id: 'beta',
    name: 'Beta',
    path: '/tmp/beta',
    source_type: 'project',
    project_id: 'beta',
    enabled: true,
    frequency: 'daily',
    retention_days: 7,
    last_run_at: null,
    next_run_at: null,
    created_at: null,
    updated_at: null,
  },
]

describe('CreateBackupModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('closes after all selected backups queue successfully', async () => {
    createSourceBackupMock.mockResolvedValue({
      task_id: 'task-1',
      status: 'queued',
      message: 'queued',
    })
    const onCreated = vi.fn().mockResolvedValue(undefined)
    const onClose = vi.fn()

    render(
      <CreateBackupModal
        sources={sources}
        onClose={onClose}
        onCreated={onCreated}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /select all/i }))
    fireEvent.click(screen.getByTestId('backup-create-confirm'))

    await waitFor(() => expect(createSourceBackupMock).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
  })

  it('keeps only failed sources selected after a partial queue confirmation loss', async () => {
    createSourceBackupMock
      .mockResolvedValueOnce({
        task_id: 'task-1',
        status: 'queued',
        message: 'queued',
      })
      .mockRejectedValueOnce(new Error('socket hang up'))
    const onCreated = vi.fn().mockResolvedValue(undefined)

    render(
      <CreateBackupModal
        sources={sources}
        onClose={vi.fn()}
        onCreated={onCreated}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /select all/i }))
    fireEvent.click(screen.getByTestId('backup-create-confirm'))

    expect(
      await screen.findByText(
        'Queued 1 backup. 1 source did not confirm: Beta. Check Backup History before retrying.',
      ),
    ).toBeInTheDocument()
    expect(onCreated).toHaveBeenCalledTimes(1)

    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes[0]).not.toBeChecked()
    expect(checkboxes[1]).toBeChecked()
  })

  it('shows an ambiguous warning instead of a hard failure when confirmations are lost', async () => {
    createSourceBackupMock.mockRejectedValue(new Error('fetch failed'))
    const onCreated = vi.fn().mockResolvedValue(undefined)
    const onClose = vi.fn()

    render(
      <CreateBackupModal
        sources={sources}
        onClose={onClose}
        onCreated={onCreated}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /select all/i }))
    fireEvent.click(screen.getByTestId('backup-create-confirm'))

    expect(
      await screen.findByText(
        'Queue confirmation was lost while creating backups. Some backups may still be starting. Check Backup History before retrying.',
      ),
    ).toBeInTheDocument()
    expect(onCreated).toHaveBeenCalledTimes(1)
    expect(onClose).not.toHaveBeenCalled()
  })
})
