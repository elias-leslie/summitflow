import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Project } from '@/lib/api'
import { ProjectAccordionItem } from './ProjectAccordionItem'

const navigationMocks = vi.hoisted(() => ({
  usePathname: vi.fn(),
}))

const permissionTierMock = vi.hoisted(() => vi.fn())

vi.mock('next/navigation', () => ({
  usePathname: navigationMocks.usePathname,
}))

vi.mock('./useProjectPermissionTier', () => ({
  useProjectPermissionTier: permissionTierMock,
}))

function buildProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 'testing-1',
    name: 'Testing 1',
    base_url: 'https://testing-1.example.com',
    health_endpoint: '/health',
    category: 'testing',
    sidebar_rank: 1,
    created_at: '2026-04-01T00:00:00Z',
    health_status: 'healthy',
    ...overrides,
  }
}

function renderItem(
  projectOverrides: Partial<Project> = {},
  {
    onToggleExpand = () => {},
    isExpanded = false,
  }: {
    onToggleExpand?: () => void
    isExpanded?: boolean
  } = {},
) {
  render(
    <ProjectAccordionItem
      project={buildProject(projectOverrides)}
      isExpanded={isExpanded}
      isActive={false}
      activeTab={null}
      onToggleExpand={onToggleExpand}
      getProjectNavHref={(projectId, item) =>
        `/projects/${projectId}${item.href}`
      }
      dragHandleProps={{ onPointerDown: () => {} }}
    />,
  )
}

describe('ProjectAccordionItem', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    navigationMocks.usePathname.mockReturnValue('/projects/testing-1')
    permissionTierMock.mockReturnValue(null)
  })

  it('keeps the drag handle out of layout flow until hover or focus', () => {
    renderItem()

    const dragHandle = screen.getByRole('button', { name: 'Reorder Testing 1' })

    expect(dragHandle.className).toContain('absolute')
    expect(dragHandle.className).toContain('opacity-0')
    expect(dragHandle.className).toContain(
      'group-hover/project-item:opacity-100',
    )
    expect(dragHandle.className).toContain(
      'group-focus-within/project-item:opacity-100',
    )
  })

  it('lets long project titles wrap instead of truncating', () => {
    const projectName =
      'Testing Project For Very Narrow Sidebar Windows With Extra Words'

    renderItem({ name: projectName })

    const title = screen.getByText(projectName)
    const link = screen.getByTestId('project-link-testing-1')

    expect(title.className).toContain('break-words')
    expect(title.className).toContain('whitespace-normal')
    expect(title.className).not.toContain('truncate')
    expect(link.className).toContain('items-start')
  })

  it('navigates to the project overview from the project header', () => {
    renderItem()

    expect(screen.getByTestId('project-link-testing-1')).toHaveAttribute(
      'href',
      '/projects/testing-1',
    )
  })

  it('uses the chevron button to expand project navigation', () => {
    const onToggleExpand = vi.fn()

    renderItem({}, { onToggleExpand })

    fireEvent.click(screen.getByTestId('project-accordion-toggle-testing-1'))

    expect(onToggleExpand).toHaveBeenCalledTimes(1)
  })

  it('keeps collapsed project navigation out of the tab and accessibility order', () => {
    renderItem()

    expect(
      screen.queryByRole('link', { name: 'Tasks' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: 'Settings' }),
    ).not.toBeInTheDocument()
  })

  it('renders project navigation links only after expansion', () => {
    renderItem({}, { isExpanded: true })

    expect(screen.getByRole('link', { name: 'Tasks' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Explorer' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Settings' })).toBeInTheDocument()
  })
})
