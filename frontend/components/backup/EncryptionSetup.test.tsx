import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  type BackupEncryptionStatus,
  exportBackupRecoveryKey,
  fetchBackupEncryption,
  importBackupRecoveryKey,
  setupBackupEncryption,
  verifyBackupRecoveryKey,
} from '@/lib/api/backups'
import { EncryptionSetup } from './EncryptionSetup'

vi.mock('@/lib/api/backups', () => ({
  exportBackupRecoveryKey: vi.fn(),
  fetchBackupEncryption: vi.fn(),
  importBackupRecoveryKey: vi.fn(),
  setupBackupEncryption: vi.fn(),
  verifyBackupRecoveryKey: vi.fn(),
}))

const pending: BackupEncryptionStatus = {
  configured: true,
  ready: false,
  key_id: 'test-key',
  roundtrip_verified_at: null,
  identity_exported: false,
  can_manage_key: true,
}

function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <EncryptionSetup />
    </QueryClientProvider>,
  )
  return client
}

describe('Backup encryption setup', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(fetchBackupEncryption).mockResolvedValue(pending)
  })

  it('can restore an existing saved key on a fresh host without generating another', async () => {
    vi.mocked(fetchBackupEncryption).mockResolvedValue({
      ...pending,
      configured: false,
      key_id: null,
    })
    vi.mocked(importBackupRecoveryKey).mockImplementation(async () => {
      const ready = { ...pending, ready: true }
      vi.mocked(fetchBackupEncryption).mockResolvedValue(ready)
      return ready
    })
    show()
    fireEvent.click(await screen.findByText('Use an existing recovery key'))
    fireEvent.change(
      screen.getByLabelText('Or paste the key from your password manager'),
      { target: { value: 'EXISTING_SAVED_KEY' } },
    )
    fireEvent.click(screen.getByRole('button', { name: 'Restore saved key' }))
    expect(await screen.findByText('Recovery key verified')).toBeInTheDocument()
    expect(importBackupRecoveryKey).toHaveBeenCalledWith('EXISTING_SAVED_KEY')
    expect(setupBackupEncryption).not.toHaveBeenCalled()
  })

  it('does not fetch a secret automatically and requires an explicit reveal', async () => {
    vi.mocked(exportBackupRecoveryKey).mockResolvedValue({
      key_id: 'test-key',
      recovery_key: 'EXAMPLE_RECOVERY_KEY',
    })
    const client = show()
    fireEvent.click(await screen.findByRole('button', { name: 'Reveal key' }))
    expect(await screen.findByLabelText('Recovery key')).toHaveTextContent(
      'EXAMPLE_RECOVERY_KEY',
    )
    expect(exportBackupRecoveryKey).toHaveBeenCalledTimes(1)
    expect(
      JSON.stringify(
        client
          .getQueryCache()
          .getAll()
          .map((entry) => entry.state.data),
      ),
    ).not.toContain('EXAMPLE_RECOVERY_KEY')
    fireEvent.click(screen.getByRole('button', { name: 'Hide key' }))
    expect(screen.queryByLabelText('Recovery key')).not.toBeInTheDocument()
  })

  it('never treats generation or export as proof the saved key works', async () => {
    show()
    expect(await screen.findByText('Setup required')).toBeInTheDocument()
    expect(exportBackupRecoveryKey).not.toHaveBeenCalled()
    expect(verifyBackupRecoveryKey).not.toHaveBeenCalled()
    expect(screen.queryByText('Recovery key verified')).not.toBeInTheDocument()
  })

  it('submits the separately saved key, then clears it after verification', async () => {
    const ready = { ...pending, ready: true, identity_exported: true }
    vi.mocked(verifyBackupRecoveryKey).mockImplementation(async () => {
      vi.mocked(fetchBackupEncryption).mockResolvedValue(ready)
      return ready
    })
    show()
    const input = await screen.findByLabelText(
      'Or paste the key from your password manager',
    )
    fireEvent.change(input, { target: { value: 'SAVED_KEY_COPY' } })
    fireEvent.click(screen.getByRole('button', { name: 'Verify saved key' }))
    expect(await screen.findByText('Recovery key verified')).toBeInTheDocument()
    expect(verifyBackupRecoveryKey).toHaveBeenCalledWith('SAVED_KEY_COPY')
    expect(input).toHaveValue('')
    expect(exportBackupRecoveryKey).not.toHaveBeenCalled()
  })

  it('clears a wrong key and reports failure without marking setup complete', async () => {
    vi.mocked(verifyBackupRecoveryKey).mockRejectedValue(
      new Error('Saved key did not decrypt the test backup'),
    )
    show()
    const input = await screen.findByLabelText(
      'Or paste the key from your password manager',
    )
    fireEvent.change(input, { target: { value: 'WRONG_KEY' } })
    fireEvent.click(screen.getByRole('button', { name: 'Verify saved key' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Saved key did not decrypt',
    )
    expect(input).toHaveValue('')
    expect(screen.getByText('Setup required')).toBeInTheDocument()
  })

  it('does not show secret actions for a local-bypass session', async () => {
    vi.mocked(fetchBackupEncryption).mockResolvedValue({
      ...pending,
      can_manage_key: false,
    })
    show()
    expect(
      await screen.findByText(/Open SummitFlow through Cloudflare Access/),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Reveal key' }),
    ).not.toBeInTheDocument()
    expect(exportBackupRecoveryKey).not.toHaveBeenCalled()
  })

  it('generates once on demand without silently retrieving the private key', async () => {
    vi.mocked(fetchBackupEncryption).mockResolvedValue({
      ...pending,
      configured: false,
      key_id: null,
    })
    vi.mocked(setupBackupEncryption).mockImplementation(async () => {
      vi.mocked(fetchBackupEncryption).mockResolvedValue(pending)
      return pending
    })
    show()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Generate recovery key' }),
    )
    await waitFor(() => expect(setupBackupEncryption).toHaveBeenCalledTimes(1))
    expect(
      await screen.findByRole('button', { name: 'Download key' }),
    ).toBeInTheDocument()
    expect(exportBackupRecoveryKey).not.toHaveBeenCalled()
  })
})
