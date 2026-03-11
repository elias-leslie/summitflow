import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ActivityFeed } from './ActivityFeed'

const fetchActivityMock = vi.fn()

vi.mock('@/lib/api/activity', () => ({
  fetchActivity: (...args: unknown[]) => fetchActivityMock(...args),
}))

vi.mock('react-window', () => ({
  List: ({
    rowComponent: RowComponent,
    rowCount,
    rowProps,
  }: {
    rowComponent: (props: { index: number; style: React.CSSProperties; items: unknown[] }) => ReactNode
    rowCount: number
    rowProps: { items: unknown[] }
  }) => (
    <div>
      {Array.from({ length: rowCount }, (_, index) => (
        <div key={index}>
          {RowComponent({ index, style: {}, items: rowProps.items })}
        </div>
      ))}
    </div>
  ),
}))

function renderFeed() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <ActivityFeed />
    </QueryClientProvider>,
  )
}

describe('ActivityFeed', () => {
  beforeEach(() => {
    fetchActivityMock.mockReset()
  })

  it('shows filter-specific empty messaging', async () => {
    fetchActivityMock.mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0, has_more: false })

    renderFeed()

    fireEvent.click(await screen.findByRole('button', { name: /git/i }))

    await waitFor(() => {
      expect(screen.getByText('No recent git activity')).toBeInTheDocument()
    })
  })

  it('shows the fetch error detail and keeps retry available', async () => {
    fetchActivityMock.mockRejectedValue(new Error('upstream timeout'))

    renderFeed()

    await waitFor(() => {
      expect(screen.getByText('Failed to load activity')).toBeInTheDocument()
    })

    expect(screen.getByText('upstream timeout')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })
})
