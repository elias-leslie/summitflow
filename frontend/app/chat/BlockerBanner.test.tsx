import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { BlockerBanner } from './BlockerBanner'

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string
    children: ReactNode
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

describe('BlockerBanner', () => {
  it('links back to the provided project task page', () => {
    render(
      <BlockerBanner
        projectId="agent-hub"
        taskId="task-123"
        notification={null}
      />,
    )

    expect(screen.getByLabelText(/back to task/i)).toHaveAttribute(
      'href',
      '/projects/agent-hub/tasks/task-123',
    )
  })
})
