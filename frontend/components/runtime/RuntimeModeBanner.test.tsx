import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RuntimeModeBanner } from './RuntimeModeBanner'

const queryMocks = vi.hoisted(() => ({
  useQuery: vi.fn(),
}))

vi.mock('@tanstack/react-query', () => ({
  useQuery: queryMocks.useQuery,
}))

describe('RuntimeModeBanner', () => {
  it('renders the hybrid runtime state with metadata', () => {
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

    render(<RuntimeModeBanner />)

    expect(screen.getByText('hybrid')).toBeInTheDocument()
    expect(screen.getByText('native')).toBeInTheDocument()
    expect(screen.getByText('docker')).toBeInTheDocument()
  })

  it('renders a runtime error state', () => {
    queryMocks.useQuery.mockReturnValue({
      data: undefined,
      error: new Error('503: runtime unavailable'),
      isLoading: false,
    })

    render(<RuntimeModeBanner />)

    expect(screen.getByText('503: runtime unavailable')).toBeInTheDocument()
  })
})
