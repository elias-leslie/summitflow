import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { makeTask } from '@/tests/factories'
import { TaskCardHeader } from './TaskCardHeader'

describe('TaskCardHeader', () => {
  it('renders task ID and priority', () => {
    render(<TaskCardHeader task={makeTask({ id: 'task-abc123', priority: 2 })} />)

    expect(screen.getByText('task-abc123')).toBeInTheDocument()
    expect(screen.getByText('P2')).toBeInTheDocument()
  })

  it('renders P1 priority with correct text', () => {
    render(<TaskCardHeader task={makeTask({ priority: 1 })} />)

    expect(screen.getByText('P1')).toBeInTheDocument()
  })

  it('shows running status indicator when running', () => {
    render(<TaskCardHeader task={makeTask({ status: 'running' })} />)

    // Running status shows an icon with a title attribute
    const statusEl = screen.getByTitle('Task running')
    expect(statusEl).toBeInTheDocument()
  })

  it('does not show running indicator for non-running tasks', () => {
    render(<TaskCardHeader task={makeTask({ status: 'pending' })} />)

    expect(screen.queryByTitle('Task running')).not.toBeInTheDocument()
  })
})
