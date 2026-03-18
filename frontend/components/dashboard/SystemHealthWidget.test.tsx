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

  it('shows error state when fetch fails', () => {
    useSystemStatsMock.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('gateway timeout'),
      refetch: vi.fn(),
      isFetching: false,
    })

    render(<SystemHealthWidget />)

    expect(screen.getByText('Metrics unavailable')).toBeInTheDocument()
    expect(screen.getByLabelText('Retry loading metrics')).toBeInTheDocument()
  })

  it('renders metric bars when data is available', () => {
    useSystemStatsMock.mockReturnValue({
      data: {
        cpu: { percent_used: 12, cores: 8, status: 'ok' },
        memory: {
          total_gb: 32,
          used_gb: 10,
          available_gb: 22,
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

    expect(screen.getByText('CPU')).toBeInTheDocument()
    expect(screen.getByText('RAM')).toBeInTheDocument()
    expect(screen.getByText('Disk')).toBeInTheDocument()
    expect(screen.getByText('12%')).toBeInTheDocument()
  })

  it('shows unavailable state when no data and no error', () => {
    useSystemStatsMock.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    })

    render(<SystemHealthWidget />)

    expect(screen.getByText('Metrics unavailable')).toBeInTheDocument()
  })

  it('shows loading spinner while fetching', () => {
    useSystemStatsMock.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    })

    render(<SystemHealthWidget />)

    expect(screen.getByText('Loading metrics...')).toBeInTheDocument()
  })
})
