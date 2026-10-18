import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ExternalBackups } from './ExternalBackups'

const mocks = vi.hoisted(() => ({ useQuery: vi.fn() }))
vi.mock('@tanstack/react-query', () => ({ useQuery: mocks.useQuery }))

describe('ExternalBackups', () => {
  it('shows each tracked backup as fresh or stale with its last good run', () => {
    mocks.useQuery.mockReturnValue({
      isLoading: false,
      error: null,
      data: {
        generated_at: new Date().toISOString(),
        sources: [
          {
            id: 'blackbox-archive',
            name: 'Blackbox off-building archive pull',
            owner_project: 'blackbox',
            kind: 'systemd_unit',
            target: 'blackbox-archive.service',
            frequency: 'daily',
            ok: true,
            stale_after_hours: 48,
            last_success_at: new Date().toISOString(),
            last_status: 'completed',
            last_error: null,
          },
          {
            id: 'portfolio-ai-complete',
            name: 'Portfolio-AI full backup',
            owner_project: 'portfolio-ai',
            kind: 'artifact_glob',
            target: '/x/portfolio_ai_complete_*.tar.gz',
            frequency: 'weekly',
            ok: false,
            stale_after_hours: 336,
            last_success_at: null,
            last_status: 'never',
            last_error: 'no backup file found',
          },
        ],
      },
    })
    render(<ExternalBackups />)
    expect(screen.getByText('Fresh')).toBeInTheDocument()
    expect(screen.getByText('Stale')).toBeInTheDocument()
    expect(screen.getByText('no backup file found')).toBeInTheDocument()
    expect(
      screen.getByText('Timer blackbox-archive.service'),
    ).toBeInTheDocument()
  })
})
