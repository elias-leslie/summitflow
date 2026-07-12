import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TopBar } from './TopBar'

const navigationMocks = vi.hoisted(() => ({
  useParams: vi.fn(),
  usePathname: vi.fn(),
}))

const notificationBellMock = vi.hoisted(() => vi.fn())
const navigationMock = vi.hoisted(() => vi.fn())
const adaptiveNavigationMock = vi.hoisted(() => vi.fn())

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

vi.mock('./topbar/AnimatedLogo', () => ({
  AnimatedLogo: () => <div data-testid="animated-logo" />,
}))

vi.mock('./MobileNavigationSheet', () => ({
  MobileNavigationSheet: ({
    open,
    onOpenChange,
  }: {
    open: boolean
    onOpenChange: (open: boolean) => void
  }) => (
    <div data-testid="mobile-navigation-sheet" data-open={open ? 'yes' : 'no'}>
      {open ? (
        <button type="button" onClick={() => onOpenChange(false)}>
          Close mobile navigation
        </button>
      ) : null}
    </div>
  ),
}))

vi.mock('./topbar/useAdaptiveNavigation', () => ({
  useAdaptiveNavigation: adaptiveNavigationMock,
}))

vi.mock('./topbar/Navigation', () => ({
  Navigation: (props: {
    compact?: boolean
    dense?: boolean
    measure?: boolean
  }) => {
    navigationMock(props)
    return (
      <nav
        data-testid={props.measure ? 'navigation-measure' : 'navigation'}
        data-compact={props.compact ? 'yes' : 'no'}
        data-dense={props.dense ? 'yes' : 'no'}
      />
    )
  },
}))

vi.mock('./topbar/TaskSearch', () => ({
  TaskSearch: (props: { onExpandedChange?: (isExpanded: boolean) => void }) => (
    <button
      type="button"
      data-testid="task-search"
      onClick={() => props.onExpandedChange?.(true)}
    />
  ),
}))

describe('TopBar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    navigationMocks.usePathname.mockReturnValue('/')
    navigationMocks.useParams.mockReturnValue({})
    adaptiveNavigationMock.mockImplementation((searchExpanded: boolean) => ({
      compact: searchExpanded,
      measureRef: { current: null },
      slotRef: { current: null },
    }))
  })

  it('uses the active project id for notifications on project pages', () => {
    navigationMocks.usePathname.mockReturnValue('/projects/agent-hub')
    navigationMocks.useParams.mockReturnValue({ id: 'agent-hub' })

    render(<TopBar />)

    expect(screen.getByTestId('notification-bell')).toHaveTextContent(
      'agent-hub',
    )
    expect(notificationBellMock).toHaveBeenCalledWith(
      expect.objectContaining({ projectId: 'agent-hub' }),
    )
  })

  it('falls back to the default project outside project routes', () => {
    render(<TopBar />)

    expect(screen.getByTestId('notification-bell')).toHaveTextContent(
      'summitflow',
    )
    expect(notificationBellMock).toHaveBeenCalledWith(
      expect.objectContaining({ projectId: 'summitflow' }),
    )
  })

  it('compacts navigation when task search expands', () => {
    render(<TopBar />)

    expect(screen.getByTestId('navigation')).toHaveAttribute(
      'data-compact',
      'no',
    )
    expect(screen.getByTestId('navigation')).toHaveAttribute('data-dense', 'no')

    fireEvent.click(screen.getByTestId('task-search'))

    expect(screen.getByTestId('navigation')).toHaveAttribute(
      'data-compact',
      'yes',
    )
    expect(screen.getByTestId('navigation')).toHaveAttribute(
      'data-dense',
      'yes',
    )
    expect(navigationMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ compact: true, dense: true }),
    )
  })

  it('renders a global files link next to topbar tools', () => {
    navigationMocks.usePathname.mockReturnValue('/files')

    render(<TopBar />)

    expect(screen.getByRole('link', { name: 'Global files' })).toHaveAttribute(
      'href',
      '/files',
    )
  })

  it('opens the mobile navigation from a dedicated labelled control', () => {
    render(<TopBar />)

    const trigger = screen.getByRole('button', { name: 'Open navigation' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(trigger)

    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByTestId('mobile-navigation-sheet')).toHaveAttribute(
      'data-open',
      'yes',
    )
  })

  it('restores focus to the mobile navigation trigger after close', async () => {
    render(<TopBar />)

    const trigger = screen.getByRole('button', { name: 'Open navigation' })
    fireEvent.click(trigger)
    fireEvent.click(
      screen.getByRole('button', { name: 'Close mobile navigation' }),
    )

    await waitFor(() => expect(trigger).toHaveFocus())
  })
})
