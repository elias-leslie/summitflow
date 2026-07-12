import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TaskQueryState } from './TaskQueryState'

describe('TaskQueryState', () => {
  it('announces loading instead of rendering an empty task surface', () => {
    render(
      <TaskQueryState
        error={null}
        isLoading
        loadingLabel="Loading task board..."
        onRetry={vi.fn()}
      >
        <div>Empty board</div>
      </TaskQueryState>,
    )

    expect(screen.getByRole('status')).toHaveTextContent(
      'Loading task board...',
    )
    expect(screen.queryByText('Empty board')).not.toBeInTheDocument()
  })

  it('shows the query error and offers a working retry', () => {
    const onRetry = vi.fn()
    render(
      <TaskQueryState
        error={new Error('Backend unavailable')}
        isLoading={false}
        loadingLabel="Loading tasks..."
        onRetry={onRetry}
      >
        <div>Empty table</div>
      </TaskQueryState>,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('Backend unavailable')
    expect(screen.queryByText('Empty table')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })
})
