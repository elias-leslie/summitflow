import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest'
import { NotificationBell } from './NotificationBell'

const sonnerMocks = vi.hoisted(() => ({
  error: vi.fn(),
}))

const apiMocks = vi.hoisted(() => ({
  dismissNotification: vi.fn(),
  fetchNotificationCount: vi.fn(),
  fetchNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  dismissNotification: apiMocks.dismissNotification,
  fetchNotificationCount: apiMocks.fetchNotificationCount,
  fetchNotifications: apiMocks.fetchNotifications,
  markNotificationRead: apiMocks.markNotificationRead,
}))

vi.mock('sonner', () => ({
  toast: sonnerMocks,
}))

vi.mock('./PushNotificationToggle', () => ({
  PushNotificationToggle: () => <div data-testid="push-toggle" />,
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
})
