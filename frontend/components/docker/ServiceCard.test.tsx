import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ServiceCard } from './ServiceCard'

vi.mock('@tanstack/react-query', () => ({
  useMutation: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
  useQueryClient: () => ({
    invalidateQueries: vi.fn(),
  }),
}))

vi.mock('@/lib/api/docker', () => ({
  dockerApi: {
    restart: vi.fn(),
    stop: vi.fn(),
    start: vi.fn(),
  },
}))

vi.mock('./LogViewer', () => ({
  LogViewer: () => <div data-testid="log-viewer" />,
}))

describe('ServiceCard', () => {
  it('renders container metrics inside the service card for running containers', () => {
    render(
      <ServiceCard
        container={{
          name: 'summitflow-stack-api-1',
          service: 'summitflow-api',
          display_name: 'summitflow-api',
          manager: 'systemd',
          category: 'app',
          state: 'running',
          health: 'healthy',
          status: 'Up 10 minutes (healthy)',
          ports: ['8000'],
        }}
        metric={{
          name: 'summitflow-backend.service',
          service: 'summitflow-api',
          cpu_percent: '3.5%',
          mem_usage: '120MiB / 2GiB',
          mem_percent: '5.8%',
          net_io: '12kB / 14kB',
          block_io: '0B / 0B',
        }}
      />,
    )

    expect(screen.getByText('CPU')).toBeInTheDocument()
    expect(screen.getByText('3.5%')).toBeInTheDocument()
    expect(screen.getByText('Memory')).toBeInTheDocument()
    expect(screen.getByText('120MiB / 2GiB')).toBeInTheDocument()
    expect(screen.getByText('Mem %')).toBeInTheDocument()
    expect(screen.getByText('5.8%')).toBeInTheDocument()
  })
})
