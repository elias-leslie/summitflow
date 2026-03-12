import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ActivityFeed } from './ActivityFeed'

const fetchActivityMock = vi.fn()

vi.mock('@/lib/api/activity', () => ({
  fetchActivity: (...args: unknown[]) => fetchActivityMock(...args),
}))

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

vi.mock('react-window', () => ({
  List: ({
    rowComponent: RowComponent,
    rowCount,
    rowProps,
  }: {
    rowComponent: (props: {
      index: number
      style: React.CSSProperties
      items: unknown[]
      nowMs: number
    }) => ReactNode
    rowCount: number
    rowProps: { items: unknown[]; nowMs: number }
  }) => (
    <div>
      {Array.from({ length: rowCount }, (_, index) => (
        <div key={index}>
          {RowComponent({
            index,
            style: {},
            items: rowProps.items,
            nowMs: rowProps.nowMs,
          })}
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
    fetchActivityMock.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0, has_more: false })

    renderFeed()

    fireEvent.click(await screen.findByRole('button', { name: /git/i }))

    await waitFor(() => {
      expect(screen.getByText('No recent git activity')).toBeInTheDocument()
    })
    expect(screen.getByText('0 items in git')).toBeInTheDocument()
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

  it('loads older activity pages and links events back to projects', async () => {
    fetchActivityMock
      .mockResolvedValueOnce({
        items: [
          {
            type: 'task',
            message: 'Initial task completed',
            timestamp: '2026-03-12T12:00:00Z',
            project_id: 'summitflow',
            metadata: { status: 'completed' },
          },
        ],
        total: 2,
        limit: 50,
        offset: 0,
        has_more: true,
      })
      .mockResolvedValueOnce({
        items: [
          {
            type: 'git',
            message: 'Older commit recorded',
            timestamp: '2026-03-12T11:00:00Z',
            project_id: 'summitflow',
            metadata: { status: 'completed' },
          },
        ],
        total: 2,
        limit: 50,
        offset: 1,
        has_more: false,
      })

    renderFeed()

    expect(await screen.findByText('Initial task completed')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'summitflow' })).toHaveAttribute(
      'href',
      '/projects/summitflow',
    )

    fireEvent.click(screen.getByRole('button', { name: /load older activity/i }))

    expect(await screen.findByText('Older commit recorded')).toBeInTheDocument()
    expect(fetchActivityMock).toHaveBeenNthCalledWith(2, {
      limit: 50,
      offset: 1,
      types: undefined,
    })
  })
})
