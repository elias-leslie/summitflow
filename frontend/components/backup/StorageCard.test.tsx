import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { StorageCard } from './StorageCard'

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string
    children: ReactNode
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('@/lib/api/backups', () => ({
  testStorageBackend: vi.fn(),
}))

describe('StorageCard', () => {
  it('shows a collapsed storage summary by default', () => {
    render(
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

    const toggle = screen.getByRole('button', { name: /storage/i })

    expect(screen.getByText('Storage')).toBeInTheDocument()
    expect(screen.getByText(/Davion-Sidar over SMB at 192.168.8.128\/davion-gem/)).toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  it('reveals backend details after expanding', () => {
    render(
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

    fireEvent.click(screen.getByRole('button', { name: /storage/i }))

    expect(screen.getByText('Name')).toBeInTheDocument()
    expect(screen.getByText('Type')).toBeInTheDocument()
    expect(screen.getAllByText('Davion-Sidar').length).toBeGreaterThan(0)
  })
})
