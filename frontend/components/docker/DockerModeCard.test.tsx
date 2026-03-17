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
  it('renders the current stack mode and switch controls', () => {
    queryMocks.useQueryClient.mockReturnValue({
      invalidateQueries: vi.fn(),
    })
    queryMocks.useQuery.mockReturnValue({
      data: {
        runtime: 'docker',
        current_mode: 'dev',
        configured_mode: 'dev',
        default_mode: 'dev',
        source: 'detected',
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

    expect(screen.getByText('Stack Mode')).toBeInTheDocument()
    expect(screen.getByText('Switch to Dev')).toBeDisabled()
    expect(screen.getByText('Switch to Prod')).toBeEnabled()
    expect(
      screen.getByText('Mode is being read from the running containers.'),
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
