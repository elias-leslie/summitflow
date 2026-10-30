import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NotificationBell } from './NotificationBell'

const sonnerMocks = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}))

const apiMocks = vi.hoisted(() => ({
  dismissAllNotifications: vi.fn(),
  dismissNotification: vi.fn(),
  fetchNotificationCount: vi.fn(),
  fetchNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  dismissAllNotifications: apiMocks.dismissAllNotifications,
  dismissNotification: apiMocks.dismissNotification,
  fetchNotificationCount: apiMocks.fetchNotificationCount,
  fetchNotifications: apiMocks.fetchNotifications,
  markNotificationRead: apiMocks.markNotificationRead,
}))

const scopeMocks = vi.hoisted(() => ({
  dismissAllGlobalNotifications: vi.fn(),
  fetchGlobalNotificationCount: vi.fn(),
  fetchGlobalNotifications: vi.fn(),
}))

vi.mock('./notificationScope', () => scopeMocks)

vi.mock('sonner', () => ({
  toast: sonnerMocks,
}))

describe('NotificationBell', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.fetchNotificationCount.mockResolvedValue(1)
    apiMocks.fetchNotifications.mockResolvedValue({
      items: [
        {
          id: 'notif-123',
          project_id: 'agent-hub',
          task_id: 'task-123',
          type: 'task_failed',
          title: 'Task failed',
          message: 'Execution stopped',
          severity: 'error',
          status: 'pending',
          metadata: {},
          created_at: '2026-03-06T13:00:00Z',
          read_at: null,
          dismissed_at: null,
        },
      ],
      total: 1,
      pending_count: 1,
    })
    apiMocks.markNotificationRead.mockResolvedValue({})
    apiMocks.dismissNotification.mockResolvedValue({})
  })

  it('marks a notification as read when clicked', async () => {
    render(<NotificationBell projectId="agent-hub" />)

    fireEvent.click(screen.getByTitle('Notifications'))

    await screen.findByText('Task failed')
    fireEvent.click(screen.getByText('Task failed'))

    await waitFor(() => {
      expect(apiMocks.markNotificationRead).toHaveBeenCalledWith(
        'agent-hub',
        'notif-123',
      )
    })
  })

  it('expands to the full message with a link to the task', async () => {
    render(<NotificationBell projectId="agent-hub" />)

    fireEvent.click(screen.getByTitle('Notifications'))

    const row = await screen.findByRole('button', { expanded: false })
    expect(screen.queryByRole('link', { name: 'Open' })).toBeNull()
    fireEvent.click(row)

    expect(row).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute(
      'href',
      '/projects/agent-hub?task=task-123',
    )
    fireEvent.click(row)
    expect(row).toHaveAttribute('aria-expanded', 'false')
  })

  it('loads the next page when more notifications exist', async () => {
    const item = (id: string) => ({
      id,
      project_id: 'summitflow',
      task_id: null,
      type: 'system',
      title: `Title ${id}`,
      message: 'Body',
      severity: 'info',
      status: 'read',
      metadata: {},
      created_at: null,
      read_at: null,
      dismissed_at: null,
    })
    scopeMocks.fetchGlobalNotificationCount.mockResolvedValue(0)
    scopeMocks.fetchGlobalNotifications
      .mockResolvedValueOnce({ items: [item('a')], total: 2, pending_count: 0 })
      .mockResolvedValueOnce({ items: [item('b')], total: 2, pending_count: 0 })

    render(<NotificationBell projectId={null} />)

    fireEvent.click(screen.getByTitle('Notifications'))
    fireEvent.click(
      await screen.findByRole('button', { name: 'Show more (1)' }),
    )

    expect(await screen.findByText('Title b')).toBeInTheDocument()
    expect(scopeMocks.fetchGlobalNotifications).toHaveBeenLastCalledWith({
      limit: 10,
      offset: 1,
    })
    expect(screen.queryByRole('button', { name: /Show more/ })).toBeNull()
  })

  it('dismisses a notification without navigating', async () => {
    render(<NotificationBell projectId="agent-hub" />)

    fireEvent.click(screen.getByTitle('Notifications'))

    await screen.findByText('Task failed')
    fireEvent.click(screen.getByTitle('Dismiss'))

    await waitFor(() => {
      expect(apiMocks.dismissNotification).toHaveBeenCalledWith(
        'agent-hub',
        'notif-123',
      )
    })
  })

  it('names the notification on its dismiss button', async () => {
    render(<NotificationBell projectId="agent-hub" />)
    fireEvent.click(screen.getByTitle('Notifications'))
    await screen.findByText('Task failed')
    expect(
      screen.getByRole('button', { name: 'Dismiss notification: Task failed' }),
    ).toBeInTheDocument()
  })

  it('asks before dismissing every notification, and Keep leaves them', async () => {
    apiMocks.dismissAllNotifications.mockResolvedValue({})
    render(<NotificationBell projectId="agent-hub" />)
    fireEvent.click(screen.getByTitle('Notifications'))
    await screen.findByText('Task failed')

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss all…' }))
    expect(screen.getByText('Dismiss every notification?')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Keep' }))
    expect(apiMocks.dismissAllNotifications).not.toHaveBeenCalled()
    expect(screen.getByText('Task failed')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss all…' }))
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss all' }))
    await waitFor(() => {
      expect(apiMocks.dismissAllNotifications).toHaveBeenCalledWith('agent-hub')
    })
  })

  it('shows a retry state when notifications fail to load', async () => {
    apiMocks.fetchNotifications.mockRejectedValueOnce(new Error('boom'))

    render(<NotificationBell projectId="agent-hub" />)

    fireEvent.click(screen.getByTitle('Notifications'))

    await screen.findByText('Failed to load notifications')
    expect(
      screen.getByRole('button', { name: 'Try again' }),
    ).toBeInTheDocument()
    expect(sonnerMocks.error).not.toHaveBeenCalled()
  })

  it('uses the global count and list when no project is selected', async () => {
    scopeMocks.fetchGlobalNotificationCount.mockResolvedValue(7)
    scopeMocks.fetchGlobalNotifications.mockResolvedValue({
      items: [],
      total: 0,
      pending_count: 7,
    })

    render(<NotificationBell projectId={null} />)

    expect(await screen.findByText('7')).toBeInTheDocument()
    expect(apiMocks.fetchNotificationCount).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTitle('Notifications'))
    await waitFor(() => {
      expect(scopeMocks.fetchGlobalNotifications).toHaveBeenCalledWith({
        limit: 10,
      })
    })
  })

  it('shows an unavailable marker instead of a count when the count fetch fails', async () => {
    apiMocks.fetchNotificationCount.mockRejectedValue(new Error('down'))

    render(<NotificationBell projectId="agent-hub" />)

    expect(
      await screen.findByTestId('notification-count-error'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Notifications (count unavailable)' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })
})
