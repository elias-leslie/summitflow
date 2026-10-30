import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DEFAULT_FILTERS, TaskFilters } from './TaskFilters'

describe('TaskFilters', () => {
  it('names each filter dropdown so it can be found by role', () => {
    const onChange = vi.fn()
    render(
      <TaskFilters
        projectId="summitflow"
        filters={DEFAULT_FILTERS}
        onChange={onChange}
      />,
    )

    fireEvent.change(
      screen.getByRole('combobox', { name: 'Filter by task type' }),
      { target: { value: 'bug,regression' } },
    )
    expect(onChange).toHaveBeenLastCalledWith({
      ...DEFAULT_FILTERS,
      type: 'bug,regression',
    })

    fireEvent.change(
      screen.getByRole('combobox', { name: 'Filter by status' }),
      { target: { value: 'active' } },
    )
    expect(onChange).toHaveBeenLastCalledWith({
      ...DEFAULT_FILTERS,
      status: 'active',
    })

    fireEvent.change(
      screen.getByRole('combobox', { name: 'Filter by priority' }),
      { target: { value: '1' } },
    )
    expect(onChange).toHaveBeenLastCalledWith({
      ...DEFAULT_FILTERS,
      priority: 1,
    })
  })
})
