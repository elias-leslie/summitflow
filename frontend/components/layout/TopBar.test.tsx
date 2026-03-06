import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TopBar } from './TopBar'

const navigationMocks = vi.hoisted(() => ({
  useParams: vi.fn(),
  usePathname: vi.fn(),
}))

const notificationBellMock = vi.hoisted(() => vi.fn())

vi.mock('next/navigation', () => ({
  useParams: navigationMocks.useParams,
  usePathname: navigationMocks.usePathname,
}))

vi.mock('@/components/notifications', () => ({
  NotificationBell: (props: { projectId: string }) => {
    notificationBellMock(props)
    return <div data-testid="notification-bell">{props.projectId}</div>
  },
}))

vi.mock('@/hooks/usePersonaName', () => ({
  usePersonaName: () => 'Jenny',
}))

vi.mock('./topbar/AnimatedLogo', () => ({
  AnimatedLogo: () => <div data-testid="animated-logo" />,
}))

vi.mock('./topbar/Navigation', () => ({
  Navigation: () => <nav data-testid="navigation" />,
}))

vi.mock('./topbar/TaskSearch', () => ({
  TaskSearch: () => <div data-testid="task-search" />,
}))

describe('TopBar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    navigationMocks.usePathname.mockReturnValue('/')
    navigationMocks.useParams.mockReturnValue({})
  })

  it('uses the active project id for notifications on project pages', () => {
    navigationMocks.usePathname.mockReturnValue('/projects/agent-hub')
    navigationMocks.useParams.mockReturnValue({ id: 'agent-hub' })

    render(<TopBar />)

    expect(screen.getByTestId('notification-bell')).toHaveTextContent('agent-hub')
    expect(notificationBellMock).toHaveBeenCalledWith(
      expect.objectContaining({ projectId: 'agent-hub' }),
    )
  })

  it('falls back to the default project outside project routes', () => {
    render(<TopBar />)

    expect(screen.getByTestId('notification-bell')).toHaveTextContent('summitflow')
    expect(notificationBellMock).toHaveBeenCalledWith(
      expect.objectContaining({ projectId: 'summitflow' }),
    )
  })
})
