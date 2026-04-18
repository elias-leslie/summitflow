import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ConfirmDeleteDialog } from './ConfirmDeleteDialog'

describe('ConfirmDeleteDialog', () => {
  const defaultProps = {
    entityType: 'task' as const,
    entityName: 'task-abc123',
    isDeleting: false,
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
  }

  it('renders task delete dialog with entity name', () => {
    render(<ConfirmDeleteDialog {...defaultProps} />)

    expect(screen.getByText('Delete Task')).toBeInTheDocument()
    expect(screen.getByText('task-abc123')).toBeInTheDocument()
    expect(screen.getByText(/permanently delete/i)).toBeInTheDocument()
  })

  it('calls onConfirm when delete button clicked', () => {
    const onConfirm = vi.fn()
    render(<ConfirmDeleteDialog {...defaultProps} onConfirm={onConfirm} />)

    fireEvent.click(screen.getByText('Delete'))
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('calls onCancel when cancel button clicked', () => {
    const onCancel = vi.fn()
    render(<ConfirmDeleteDialog {...defaultProps} onCancel={onCancel} />)

    fireEvent.click(screen.getByText('Cancel'))
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('shows loading state when isDeleting is true', () => {
    render(<ConfirmDeleteDialog {...defaultProps} isDeleting={true} />)

    expect(screen.getByText('Deleting...')).toBeInTheDocument()
    expect(screen.getByText('Cancel')).toBeDisabled()
  })

  it('shows error message when isError is true', () => {
    render(<ConfirmDeleteDialog {...defaultProps} isError={true} />)

    expect(
      screen.getByText('Failed to delete task. Please try again.'),
    ).toBeInTheDocument()
  })

  it('renders bulk task delete with count', () => {
    render(
      <ConfirmDeleteDialog
        entityType="tasks"
        taskIds={new Set(['t1', 't2', 't3'])}
        isDeleting={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByText('Delete 3 Tasks')).toBeInTheDocument()
    expect(screen.getByText('Delete 3')).toBeInTheDocument()
  })

  it('renders mockup delete dialog', () => {
    render(
      <ConfirmDeleteDialog
        entityType="mockup"
        entityName="Hero Section"
        isDeleting={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByText('Delete mockup?')).toBeInTheDocument()
    expect(screen.getByText(/Hero Section/)).toBeInTheDocument()
  })

  it('renders feedback delete dialog', () => {
    render(
      <ConfirmDeleteDialog
        entityType="feedback"
        entityName="Improve CLI UX"
        isDeleting={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByText('Delete Feedback')).toBeInTheDocument()
    expect(screen.getByText(/Improve CLI UX/)).toBeInTheDocument()
  })

  it('truncates bulk task IDs beyond 5', () => {
    const ids = new Set(['t1', 't2', 't3', 't4', 't5', 't6', 't7'])
    render(
      <ConfirmDeleteDialog
        entityType="tasks"
        taskIds={ids}
        isDeleting={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByText('...and 2 more')).toBeInTheDocument()
  })

  it('cancels on backdrop click for task dialog', () => {
    const onCancel = vi.fn()
    const { container } = render(
      <ConfirmDeleteDialog {...defaultProps} onCancel={onCancel} />,
    )

    // Click the outer backdrop div
    const backdrop = container.firstChild as HTMLElement
    fireEvent.click(backdrop)
    expect(onCancel).toHaveBeenCalled()
  })

  it('does not cancel when clicking inside dialog', () => {
    const onCancel = vi.fn()
    render(<ConfirmDeleteDialog {...defaultProps} onCancel={onCancel} />)

    fireEvent.click(screen.getByText('Delete Task'))
    expect(onCancel).not.toHaveBeenCalled()
  })
})
