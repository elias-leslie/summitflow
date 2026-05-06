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
          name: 'Local Backup Drive',
          backend_type: 'local',
          is_default: true,
          enabled: true,
          last_test_at: null,
          last_test_ok: true,
          created_at: null,
          updated_at: null,
          config: {
            root_path: '/media/kasadis/Backups/davion-gem',
            path: 'project-backups',
          },
        },
      ]}
      storageStatus={{
        configured: true,
        backend_count: 1,
        default_backend_id: 'storage-1',
        default_backend_name: 'Local Backup Drive',
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
      screen.getByText(
        /Local Backup Drive over LOCAL at \/media\/kasadis\/Backups\/davion-gem\/project-backups/,
      ),
    ).toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  it('reveals backend details after expanding', () => {
    renderStorageCard()

    fireEvent.click(screen.getByRole('button', { name: /storage/i }))

    expect(screen.getByText('Name')).toBeInTheDocument()
    expect(screen.getByText('Type')).toBeInTheDocument()
    expect(screen.getAllByText('Local Backup Drive').length).toBeGreaterThan(0)
  })
})
