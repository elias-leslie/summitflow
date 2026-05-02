import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { StorageCard } from './StorageCard'

vi.mock('@/lib/api/backups', () => ({
  testStorageBackend: vi.fn(),
}))

function renderStorageCard() {
  return render(
    <StorageCard
      backends={[
        {
          id: 'storage-1',
          name: 'Davion-Sidar',
          backend_type: 'smb',
          is_default: true,
          enabled: true,
          last_test_at: null,
          last_test_ok: true,
          created_at: null,
          updated_at: null,
          config: {
            host: '192.168.8.128',
            share: 'davion-gem',
          },
        },
      ]}
      storageStatus={{
        configured: true,
        backend_count: 1,
        default_backend_id: 'storage-1',
        default_backend_name: 'Davion-Sidar',
      }}
      onRefresh={() => {}}
    />,
  )
}

describe('StorageCard', () => {
  it('shows a collapsed storage summary by default', () => {
    renderStorageCard()

    const toggle = screen.getByRole('button', { name: /storage/i })

    expect(screen.getByText('Storage')).toBeInTheDocument()
    expect(
      screen.getByText(/Davion-Sidar over SMB at 192.168.8.128\/davion-gem/),
    ).toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  it('reveals backend details after expanding', () => {
    renderStorageCard()

    fireEvent.click(screen.getByRole('button', { name: /storage/i }))

    expect(screen.getByText('Name')).toBeInTheDocument()
    expect(screen.getByText('Type')).toBeInTheDocument()
    expect(screen.getAllByText('Davion-Sidar').length).toBeGreaterThan(0)
  })
})
