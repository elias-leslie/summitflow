import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Task } from '@/lib/api'
import { TasksTabTable } from './TasksTabTable'

const task: Task = {
  id: 'task-mobile',
  project_id: 'summitflow',
  capability_id: null,
  title: 'Responsive task row',
  description: '',
  status: 'pending',
  plan_content: null,
  progress_log: null,
  error_message: null,
  branch_name: null,
  commits: [],
  total_sessions: 0,
  total_tokens_used: 0,
  created_at: null,
  updated_at: null,
  started_at: null,
  completed_at: null,
  priority: 1,
  task_type: 'bug',
  labels: [],
  parent_task_id: null,
}

describe('TasksTabTable', () => {
  it('keeps task identity and row actions usable in the compact table layout', () => {
    render(
      <TasksTabTable
        tasks={[task]}
        error={null}
        isLoading={false}
        onRetry={vi.fn()}
        sortField="updated_at"
        sortDirection="desc"
        onSort={vi.fn()}
        selectedTaskIds={new Set()}
        onToggleSelect={vi.fn()}
        onToggleSelectAll={vi.fn()}
        onTaskClick={vi.fn()}
        onDeleteClick={vi.fn()}
      />,
    )

    expect(
      screen
        .getAllByText('task-mobile')
        .some((element) =>
          element.parentElement?.classList.contains('sm:hidden'),
        ),
    ).toBe(true)
    expect(
      screen.getByRole('checkbox', { name: 'Select Responsive task row' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Delete Responsive task row' }),
    ).toBeInTheDocument()
  })
})
