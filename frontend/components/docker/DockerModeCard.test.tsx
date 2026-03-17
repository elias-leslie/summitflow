import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DockerModeCard } from './DockerModeCard'

const queryMocks = vi.hoisted(() => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useQueryClient: vi.fn(),
}))

vi.mock('@tanstack/react-query', () => ({
  useQuery: queryMocks.useQuery,
  useMutation: queryMocks.useMutation,
  useQueryClient: queryMocks.useQueryClient,
}))

describe('DockerModeCard', () => {
  it('renders the hybrid runtime state and saved docker preference controls', () => {
    queryMocks.useQueryClient.mockReturnValue({
      invalidateQueries: vi.fn(),
    })
    queryMocks.useQuery.mockReturnValue({
      data: {
        runtime: 'hybrid',
        apps_runtime: 'native',
        infra_runtime: 'docker',
        current_mode: 'dev',
        configured_mode: 'dev',
        default_mode: 'dev',
        source: 'persisted',
        is_running: true,
      },
      error: undefined,
      isLoading: false,
    })
    queryMocks.useMutation.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
      isSuccess: false,
      error: undefined,
      data: undefined,
    })

    render(<DockerModeCard />)

    expect(screen.getByText('Runtime Mode')).toBeInTheDocument()
    expect(screen.getByText('Prefer Docker Dev')).toBeDisabled()
    expect(screen.getByText('Prefer Docker Prod')).toBeEnabled()
    expect(
      screen.getByText(
        'Apps are running natively under systemd --user while PostgreSQL, Redis, and Hatchet stay in Docker.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'No app containers are running. This is the saved Docker parity preference.',
      ),
    ).toBeInTheDocument()
  })

  it('renders a runtime error state', () => {
    queryMocks.useQueryClient.mockReturnValue({
      invalidateQueries: vi.fn(),
    })
    queryMocks.useQuery.mockReturnValue({
      data: undefined,
      error: new Error('503: runtime unavailable'),
      isLoading: false,
    })
    queryMocks.useMutation.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
      isSuccess: false,
      error: undefined,
      data: undefined,
    })

    render(<DockerModeCard />)

    expect(screen.getByText('503: runtime unavailable')).toBeInTheDocument()
  })
})
