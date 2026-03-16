import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TaskSearch } from './TaskSearch'

const mediaQueryMocks = vi.hoisted(() => ({
  useIsXl: vi.fn(),
}))

const routerMocks = vi.hoisted(() => ({
  push: vi.fn(),
}))

vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({ data: null }),
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
  useSelectedProject: () => null,
}))

describe('TaskSearch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
})
