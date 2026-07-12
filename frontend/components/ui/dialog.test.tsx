import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from './dialog'

function DialogFixture({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open task details
      </button>
      <Dialog
        open={open}
        onOpenChange={(nextOpen) => {
          setOpen(nextOpen)
          if (!nextOpen) onClose()
        }}
      >
        <DialogContent>
          <DialogTitle>Task details</DialogTitle>
          <DialogDescription>Accessible modal fixture</DialogDescription>
          <button type="button">Secondary action</button>
          <DialogClose />
        </DialogContent>
      </Dialog>
    </>
  )
}

describe('Dialog', () => {
  it('traps focus, closes on Escape, and restores the opening control', async () => {
    const onClose = vi.fn()
    render(<DialogFixture onClose={onClose} />)
    const trigger = screen.getByRole('button', { name: 'Open task details' })

    trigger.focus()
    fireEvent.click(trigger)

    const dialog = screen.getByRole('dialog', { name: 'Task details' })
    const close = screen.getByRole('button', { name: 'Close dialog' })
    const secondary = screen.getByRole('button', { name: 'Secondary action' })
    await waitFor(() => expect(secondary).toHaveFocus())

    close.focus()
    fireEvent.keyDown(close, { key: 'Tab' })
    expect(secondary).toHaveFocus()

    fireEvent.keyDown(dialog, { key: 'Escape' })

    expect(onClose).toHaveBeenCalledOnce()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })
})
