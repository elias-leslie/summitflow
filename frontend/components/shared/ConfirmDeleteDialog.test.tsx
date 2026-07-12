import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog'
import { ConfirmDeleteDialog } from './ConfirmDeleteDialog'

function NestedConfirmFixture({
  onParentClose,
}: {
  onParentClose: () => void
}) {
  const [parentOpen, setParentOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)

  return (
    <>
      <button type="button" onClick={() => setParentOpen(true)}>
        Open task details
      </button>
      <Dialog
        open={parentOpen}
        onOpenChange={(open) => {
          setParentOpen(open)
          if (!open) onParentClose()
        }}
      >
        <DialogContent>
          <DialogTitle>Task details</DialogTitle>
          <DialogDescription>Nested confirmation fixture</DialogDescription>
          <button type="button" onClick={() => setConfirmOpen(true)}>
            Delete current task
          </button>
          {confirmOpen && (
            <ConfirmDeleteDialog
              entityType="task"
              entityName="task-abc123"
              isDeleting={false}
              onConfirm={vi.fn()}
              onCancel={() => setConfirmOpen(false)}
            />
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}

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
    render(<ConfirmDeleteDialog {...defaultProps} onCancel={onCancel} />)

    fireEvent.click(screen.getByTestId('confirm-delete-backdrop'))
    expect(onCancel).toHaveBeenCalled()
  })

  it('does not cancel when clicking inside dialog', () => {
    const onCancel = vi.fn()
    render(<ConfirmDeleteDialog {...defaultProps} onCancel={onCancel} />)

    fireEvent.click(screen.getByText('Delete Task'))
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('traps focus independently, closes on Escape, and restores focus in a parent dialog', async () => {
    const onParentClose = vi.fn()
    render(<NestedConfirmFixture onParentClose={onParentClose} />)

    const parentTrigger = screen.getByRole('button', {
      name: 'Open task details',
    })
    parentTrigger.focus()
    fireEvent.click(parentTrigger)

    const deleteTrigger = screen.getByRole('button', {
      name: 'Delete current task',
    })
    await waitFor(() => expect(deleteTrigger).toHaveFocus())
    fireEvent.click(deleteTrigger)

    const alertDialog = screen.getByRole('alertdialog', {
      name: 'Delete Task',
    })
    const cancel = screen.getByRole('button', { name: 'Cancel' })
    await waitFor(() => expect(cancel).toHaveFocus())
    expect(alertDialog).toContainElement(document.activeElement as HTMLElement)

    fireEvent.keyDown(alertDialog, { key: 'Escape' })

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Task details' })).toBeVisible()
    expect(onParentClose).not.toHaveBeenCalled()
    await waitFor(() => expect(deleteTrigger).toHaveFocus())
  })

  it('does not dismiss with Escape while deletion is pending', () => {
    const onCancel = vi.fn()
    render(
      <ConfirmDeleteDialog
        {...defaultProps}
        isDeleting={true}
        onCancel={onCancel}
      />,
    )

    fireEvent.keyDown(screen.getByRole('alertdialog'), { key: 'Escape' })

    expect(onCancel).not.toHaveBeenCalled()
    expect(screen.getByRole('alertdialog')).toBeVisible()
  })
})
