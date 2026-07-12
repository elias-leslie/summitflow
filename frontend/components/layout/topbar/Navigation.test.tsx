import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Navigation } from './Navigation'

vi.mock('next/navigation', () => ({
  usePathname: () => '/',
}))

vi.mock('@/hooks/useGitHealth', () => ({
  useGitHealth: () => 'clean',
}))

vi.mock('./GitStatusIndicator', () => ({
  GitStatusIndicator: () => <span data-testid="git-status" />,
}))

describe('Navigation', () => {
  it('hides nav labels in compact mode so search can take the header space', () => {
    const { container } = render(<Navigation compact />)

    expect(screen.getAllByText('Runtime')[0]).toHaveClass('hidden')
    expect(screen.getAllByText('Feedback')[0]).toHaveClass('hidden')
    expect(screen.getAllByText('Work Chats')[0]).toHaveClass('hidden')
    expect(container.querySelector('nav')).toHaveClass('justify-center')
  })

  it('keeps labels visible and shifts left in dense mode before compacting', () => {
    const { container } = render(<Navigation dense />)

    expect(screen.getAllByText('Runtime')[0]).toHaveClass('inline')
    expect(screen.getAllByText('Feedback')[0]).toHaveClass('inline')
    expect(screen.getAllByText('Work Chats')[0]).toHaveClass('inline')
    expect(container.querySelector('nav')).toHaveClass('justify-start')
  })

  it('renders the existing global destinations as a stacked mobile menu', () => {
    const { container } = render(<Navigation stacked />)

    expect(container.querySelector('nav')).toHaveClass(
      'flex-col',
      'items-stretch',
    )
    expect(screen.getByRole('link', { name: /dashboard/i })).toHaveAttribute(
      'href',
      '/',
    )
    expect(screen.getByRole('link', { name: /work chats/i })).toHaveAttribute(
      'href',
      '/work-chats',
    )
    expect(screen.getByText('Runtime')).toHaveClass('inline')
  })

  it('measures labels without rendering a second set of prefetching links', () => {
    const { container } = render(<Navigation measure />)

    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(container.querySelectorAll('nav > span')).toHaveLength(6)
    expect(screen.getByText('Runtime')).toBeInTheDocument()
  })
})
