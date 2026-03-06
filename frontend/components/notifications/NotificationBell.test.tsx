import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest'
import * as NotificationBellModule from './NotificationBell'

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

    window.history.replaceState({}, '', '/')
  })

  it('preserves project context when redirecting a deep link to chat', async () => {
    const navigateSpy = vi
      .spyOn(NotificationBellModule.browserNavigator, 'go')
      .mockImplementation(() => {})

    window.history.replaceState({}, '', '/?project_id=agent-hub&task_id=task-123&notification_id=notif-123')

    render(<NotificationBellModule.NotificationBell projectId="agent-hub" />)

    await waitFor(() => {
      expect(navigateSpy).toHaveBeenCalledWith(
        '/chat?project_id=agent-hub&task_id=task-123&notification_id=notif-123',
      )
    })
  })

  it('navigates to project-aware chat links when a notification is clicked', async () => {
    const navigateSpy = vi
      .spyOn(NotificationBellModule.browserNavigator, 'go')
      .mockImplementation(() => {})

    render(<NotificationBellModule.NotificationBell projectId="agent-hub" />)

    fireEvent.click(screen.getByTitle('Notifications'))

    await screen.findByText('Task failed')
    fireEvent.click(screen.getByText('Task failed'))

    await waitFor(() => {
      expect(apiMocks.markNotificationRead).toHaveBeenCalledWith(
        'agent-hub',
        'notif-123',
      )
      expect(navigateSpy).toHaveBeenCalledWith(
        '/chat?project_id=agent-hub&task_id=task-123&notification_id=notif-123',
      )
    })
  })
})
