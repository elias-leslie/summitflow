import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TaskSearch } from './TaskSearch'

const mediaQueryMocks = vi.hoisted(() => ({
  useIsXl: vi.fn(),
}))

const routerMocks = vi.hoisted(() => ({
  push: vi.fn(),
}))

const queryMocks = vi.hoisted(() => ({
  state: { data: null, isError: false, isPending: false } as Record<
    string,
    unknown
  >,
  project: null as string | null,
}))

vi.mock('@tanstack/react-query', () => ({
  useQuery: () => queryMocks.state,
}))

vi.mock('next/navigation', () => ({
  useRouter: () => routerMocks,
}))

vi.mock('@/lib/api', () => ({
  fetchTasks: vi.fn(),
}))

vi.mock('@/hooks/useMediaQuery', () => ({
  useIsXl: mediaQueryMocks.useIsXl,
}))

vi.mock('../ProjectSelector', () => ({
  useSelectedProject: () => queryMocks.project,
}))

describe('TaskSearch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    queryMocks.state = { data: null, isError: false, isPending: false }
    queryMocks.project = null
  })

  it('renders a compact search button below the wide desktop breakpoint', () => {
    mediaQueryMocks.useIsXl.mockReturnValue(false)

    render(<TaskSearch />)

    expect(
      screen.getByRole('button', { name: 'Search tasks' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('textbox', { name: 'Search tasks' }),
    ).not.toBeInTheDocument()
  })

  it('renders the inline search field at the wide desktop breakpoint', () => {
    mediaQueryMocks.useIsXl.mockReturnValue(true)

    render(<TaskSearch />)

    expect(
      screen.getByRole('textbox', { name: 'Search tasks' }),
    ).toBeInTheDocument()
  })

  it('reports when the inline search expands', () => {
    mediaQueryMocks.useIsXl.mockReturnValue(true)
    const onExpandedChange = vi.fn()

    render(<TaskSearch onExpandedChange={onExpandedChange} />)

    fireEvent.focus(screen.getByRole('textbox', { name: 'Search tasks' }))

    expect(onExpandedChange).toHaveBeenLastCalledWith(true)
  })

  function typeInto(value: string) {
    mediaQueryMocks.useIsXl.mockReturnValue(true)
    render(<TaskSearch />)
    const input = screen.getByRole('textbox', { name: 'Search tasks' })
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value } })
  }

  it('says search needs a project instead of claiming no tasks exist', () => {
    typeInto('lease')
    expect(screen.getByRole('status')).toHaveTextContent(
      'Open a project to search its tasks',
    )
  })

  it('names the project it searched and shows searching while loading', () => {
    queryMocks.project = 'ominull'
    queryMocks.state = { data: undefined, isError: false, isPending: true }
    typeInto('lease')
    expect(screen.getByRole('status')).toHaveTextContent('Searching…')
    expect(screen.getByRole('textbox')).toHaveAttribute(
      'placeholder',
      'Search ominull tasks…',
    )
  })

  it('reports no match within the named project', () => {
    queryMocks.project = 'ominull'
    queryMocks.state = {
      data: { tasks: [{ id: 'task-1', title: 'Other', description: null }] },
      isError: false,
      isPending: false,
    }
    typeInto('lease')
    expect(screen.getByRole('status')).toHaveTextContent(
      'No ominull tasks match',
    )
  })
})
