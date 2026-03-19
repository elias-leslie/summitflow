import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Task } from '@/lib/api'
import { TaskCardHeader } from './TaskCardHeader'

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 'task-abc123',
    project_id: 'summitflow',
    capability_id: null,
    title: 'Fix login bug',
    description: null,
    status: 'pending',
    plan_content: null,
    progress_log: null,
    error_message: null,
    branch_name: null,
    commits: [],
    total_sessions: 0,
    total_tokens_used: 0,
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
    started_at: null,
    completed_at: null,
    priority: 2,
    labels: [],
    task_type: 'bug',
    parent_task_id: null,
    ...overrides,
  }
}

describe('TaskCardHeader', () => {
  it('renders task ID and priority', () => {
    render(<TaskCardHeader task={makeTask()} />)

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
