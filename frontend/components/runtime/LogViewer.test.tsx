import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LogViewer } from './LogViewer'

const query = vi.hoisted(() => vi.fn())
vi.mock('@tanstack/react-query', () => ({ useQuery: query }))

describe('LogViewer', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    cleanup()
    act(() => vi.runOnlyPendingTimers())
    vi.useRealTimers()
  })

  it('offers recent guest logs without an unavailable stream control', () => {
    query.mockReturnValue({ data: { logs: 'Guest observation' } })
    render(
      <LogViewer service="guest-api" canStream={false} onClose={vi.fn()} />,
    )
    expect(screen.getByText('Guest observation')).toBeInTheDocument()
    expect(screen.getByText(/Recent logs only/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Stream live' })).toBeNull()
  })

  it('keeps live streaming available for local services', () => {
    query.mockReturnValue({ data: { logs: 'Local observation' } })
    render(<LogViewer service="local-api" onClose={vi.fn()} />)
    expect(
      screen.getByRole('button', { name: 'Stream live' }),
    ).toBeInTheDocument()
  })

  it('distinguishes a failed log read from an empty journal', () => {
    query.mockReturnValue({ error: new Error('Guest unavailable') })
    render(
      <LogViewer service="guest-api" canStream={false} onClose={vi.fn()} />,
    )
    expect(
      screen.getByText('Could not load logs: Guest unavailable'),
    ).toBeInTheDocument()
    expect(screen.queryByText('No logs available')).toBeNull()
  })
})
