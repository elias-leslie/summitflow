import { fireEvent, render, screen } from '@testing-library/react'
import { forwardRef, type HTMLAttributes, type ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { MobileNavigationSheet } from './MobileNavigationSheet'

const projectsAccordionMock = vi.hoisted(() => vi.fn())

vi.mock('next/navigation', () => ({
  usePathname: () => '/projects/summitflow',
}))

vi.mock('motion/react', () => ({
  AnimatePresence: ({ children }: { children: ReactNode }) => children,
  motion: {
    div: forwardRef<
      HTMLDivElement,
      HTMLAttributes<HTMLDivElement> & {
        children?: ReactNode
        initial?: unknown
        animate?: unknown
        exit?: unknown
        transition?: unknown
      }
    >(function MotionDiv(
      {
        initial: _initial,
        animate: _animate,
        exit: _exit,
        transition: _transition,
        ...props
      },
      ref,
    ) {
      return <div ref={ref} {...props} />
    }),
  },
}))

vi.mock('./topbar/Navigation', () => ({
  Navigation: ({ stacked }: { stacked?: boolean }) => (
    <nav data-stacked={stacked ? 'yes' : 'no'}>
      <a href="/">Dashboard</a>
      <a href="/git">Git</a>
    </nav>
  ),
}))

vi.mock('./sidebar/SidebarHeader', () => ({
  SidebarHeader: () => <div>Projects</div>,
}))

vi.mock('./sidebar/ProjectsAccordion', () => ({
  ProjectsAccordion: (props: {
    expandedProjectId: string | null
    onExpandProject: (projectId: string | null) => void
  }) => {
    projectsAccordionMock(props)
    return <a href="/projects/summitflow?tab=tasks">SummitFlow tasks</a>
  },
}))

describe('MobileNavigationSheet', () => {
  it('does not expose navigation while closed', () => {
    render(<MobileNavigationSheet open={false} onOpenChange={vi.fn()} />)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('combines global and current-project navigation when open', () => {
    render(<MobileNavigationSheet open onOpenChange={vi.fn()} />)

    expect(
      screen.getByRole('dialog', { name: 'Navigation' }),
    ).toHaveAccessibleDescription('Global tools and project workspaces')
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute(
      'href',
      '/',
    )
    expect(screen.getByRole('link', { name: 'Git' })).toHaveAttribute(
      'href',
      '/git',
    )
    expect(
      screen.getByRole('link', { name: 'SummitFlow tasks' }),
    ).toHaveAttribute('href', '/projects/summitflow?tab=tasks')
    expect(projectsAccordionMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ expandedProjectId: 'summitflow' }),
    )
  })

  it('closes after choosing any navigation link', () => {
    const onOpenChange = vi.fn()
    render(<MobileNavigationSheet open onOpenChange={onOpenChange} />)

    fireEvent.click(screen.getByRole('link', { name: 'Git' }))

    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
