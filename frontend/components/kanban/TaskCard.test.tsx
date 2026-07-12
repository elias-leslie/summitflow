import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Task } from '@/lib/api'
import { TaskCard } from './TaskCard'

vi.mock('@dnd-kit/sortable', () => ({
  useSortable: () => ({
    attributes: {},
    listeners: {},
    setNodeRef: vi.fn(),
    transform: null,
    transition: undefined,
    isDragging: false,
  }),
}))

const task: Task = {
  id: 'task-123',
  project_id: 'summitflow',
  capability_id: null,
  title: 'Keyboard reachable task',
  description: 'A task card fixture',
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
  priority: 2,
  task_type: 'task',
  labels: [],
  parent_task_id: null,
}

describe('TaskCard', () => {
  it('exposes the primary card action as a native keyboard-focusable button', () => {
    const onClick = vi.fn()
    render(<TaskCard task={task} onClick={onClick} />)

    const openButton = screen.getByRole('button', {
      name: 'Open task task-123: Keyboard reachable task',
    })
    openButton.focus()

    expect(openButton).toHaveFocus()
    expect(openButton.tagName).toBe('BUTTON')
  })
})
