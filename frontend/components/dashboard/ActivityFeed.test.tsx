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
      showProjectLink: boolean
    }) => ReactNode
    rowCount: number
    rowProps: { items: unknown[]; showProjectLink: boolean }
  }) => (
    <div>
      {Array.from({ length: rowCount }, (_, index) => (
        <div key={index}>
          {RowComponent({
            index,
            style: {},
            items: rowProps.items,
            showProjectLink: rowProps.showProjectLink,
          })}
        </div>
      ))}
    </div>
  ),
}))

function renderFeed(projectId?: string) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <ActivityFeed projectId={projectId} />
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
      project_id: undefined,
      types: undefined,
    })
  })

  it('scopes queries and row chrome to a single project overview', async () => {
    fetchActivityMock.mockResolvedValue({
      items: [
        {
          type: 'task',
          message: 'Task created: Restore recent activity',
          timestamp: '2026-04-04T12:00:00Z',
          project_id: 'summitflow',
          metadata: { status: 'pending' },
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
    })

    renderFeed('summitflow')

    expect(await screen.findByText('Task created: Restore recent activity')).toBeInTheDocument()
    expect(fetchActivityMock).toHaveBeenCalledWith({
      limit: 50,
      offset: 0,
      project_id: 'summitflow',
      types: undefined,
    })
    expect(screen.getByText('1 item for this project')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'summitflow' })).not.toBeInTheDocument()
  })
})
