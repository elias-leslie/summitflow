import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SystemHealthWidget } from './SystemHealthWidget'

const useSystemStatsMock = vi.fn()

vi.mock('@/hooks/useSystemStats', () => ({
  useSystemStats: () => useSystemStatsMock(),
}))

describe('SystemHealthWidget', () => {
  beforeEach(() => {
    useSystemStatsMock.mockReset()
  })

  it('surfaces fetch errors with actionable detail', () => {
    useSystemStatsMock.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('gateway timeout'),
      refetch: vi.fn(),
      isFetching: false,
    })

    render(<SystemHealthWidget />)

    expect(screen.getByText('System metrics unavailable')).toBeInTheDocument()
    expect(screen.getByText('gateway timeout')).toBeInTheDocument()
  })

  it('shows the last update timestamp when data is available', () => {
    useSystemStatsMock.mockReturnValue({
      data: {
        cpu: { percent_used: 12, cores: 8, status: 'ok' },
        memory: {
          total_gb: 32,
          used_gb: 10.2,
          available_gb: 21.8,
          percent_used: 32,
          status: 'ok',
        },
        disk: {
          total_gb: 512,
          used_gb: 121,
          free_gb: 391,
          percent_used: 24,
          status: 'ok',
        },
        timestamp: '2026-03-11T15:30:00Z',
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    })

    render(<SystemHealthWidget />)

    expect(screen.getByText(/updated/i)).toBeInTheDocument()
    expect(screen.getByText('8 cores')).toBeInTheDocument()
  })
})
