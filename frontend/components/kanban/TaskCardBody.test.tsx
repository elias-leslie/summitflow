import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Task } from '@/lib/api'
import { TaskCardBody } from './TaskCardBody'

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 'task-abc123',
    project_id: 'summitflow',
    capability_id: null,
    title: 'Implement search feature',
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
    started_at: null,
    completed_at: null,
    priority: 2,
    labels: [],
    task_type: 'feature',
    parent_task_id: null,
    ...overrides,
  }
}

describe('TaskCardBody', () => {
  it('renders task title', () => {
    render(
      <TaskCardBody task={makeTask()} canExpand={false} />,
    )

    expect(screen.getByText('Implement search feature')).toBeInTheDocument()
  })

  it('shows Standalone label when no capability', () => {
    render(
      <TaskCardBody task={makeTask()} canExpand={false} />,
    )

    expect(screen.getByText('Standalone')).toBeInTheDocument()
  })

  it('shows capability info when present', () => {
    render(
      <TaskCardBody
        task={makeTask({
          capability: {
            id: 1,
            capability_id: 'cap-search',
            name: 'Search',
            criteria_passed: 2,
            criteria_total: 5,
          },
        })}
        canExpand={false}
      />,
    )

    expect(screen.getByText('cap-search')).toBeInTheDocument()
    expect(screen.getByText('(2/5)')).toBeInTheDocument()
  })

  it('shows running step when running with currentStep', () => {
    render(
      <TaskCardBody
        task={makeTask({ status: 'running' })}
        currentStep="Running tests..."
        canExpand={false}
      />,
    )

    expect(screen.getByText('Running tests...')).toBeInTheDocument()
  })

  it('does not show step indicator when not running', () => {
    render(
      <TaskCardBody
        task={makeTask({ status: 'pending' })}
        currentStep="Some step"
        canExpand={false}
      />,
    )

    expect(screen.queryByText('Some step')).not.toBeInTheDocument()
  })
})
