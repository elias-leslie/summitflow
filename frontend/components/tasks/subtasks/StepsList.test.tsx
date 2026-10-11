import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Subtask } from '@/lib/api/tasks'
import { StepsList } from './StepsList'

function subtask(overrides: Partial<Subtask>): Subtask {
  return {
    id: 'task-1-1.1',
    task_id: 'task-1',
    subtask_id: '1.1',
    phase: 'implement',
    description: 'Fix it',
    steps: [],
    passes: false,
    passed_at: null,
    display_order: 0,
    created_at: null,
    ...overrides,
  }
}

describe('StepsList', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders plan-context steps from the subtask payload without fetching', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    // The API returns plan-context steps as objects, not strings.
    const planSteps = [
      { step_number: 1, description: 'Reproduce the bug', passes: true },
      { step_number: 2, description: 'Fix the root cause', passes: false },
    ] as unknown as string[]

    render(<StepsList subtask={subtask({ steps: planSteps })} />)

    expect(screen.getByText('Reproduce the bug')).toBeInTheDocument()
    expect(screen.getByText('Fix the root cause')).toBeInTheDocument()
    expect(screen.getByText('1/2')).toBeInTheDocument()
    expect(screen.getByLabelText('Step complete')).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('accepts legacy string steps', () => {
    render(
      <StepsList subtask={subtask({ steps: ['First thing', 'Second'] })} />,
    )

    expect(screen.getByText('First thing')).toBeInTheDocument()
    expect(screen.getByText('0/2')).toBeInTheDocument()
  })

  it('shows an empty state when the subtask has no steps', () => {
    render(<StepsList subtask={subtask({ steps: [] })} />)

    expect(screen.getByText('No steps defined')).toBeInTheDocument()
  })
})
