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
    expect(screen.getAllByText('Design')[0]).toHaveClass('hidden')
    expect(container.querySelector('nav')).toHaveClass('justify-center')
  })

  it('keeps labels visible and shifts left in dense mode before compacting', () => {
    const { container } = render(<Navigation dense />)

    expect(screen.getAllByText('Runtime')[0]).toHaveClass('inline')
    expect(screen.getAllByText('Feedback')[0]).toHaveClass('inline')
    expect(screen.getAllByText('Design')[0]).toHaveClass('inline')
    expect(container.querySelector('nav')).toHaveClass('justify-start')
  })
})
