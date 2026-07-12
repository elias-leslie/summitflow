import { fireEvent, render, screen } from '@testing-library/react'
import {
  forwardRef,
  type HTMLAttributes,
  type ReactNode,
  useState,
} from 'react'
import { describe, expect, it, vi } from 'vitest'
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from './sheet'

vi.mock('motion/react', () => ({
  motion: {
    div: forwardRef<
      HTMLDivElement,
      HTMLAttributes<HTMLDivElement> & {
        children?: ReactNode
        initial?: unknown
        animate?: unknown
        transition?: unknown
      }
    >(function MotionDiv(
      {
        initial: _initial,
        animate: _animate,
        transition: _transition,
        ...props
      },
      ref,
    ) {
      return <div ref={ref} {...props} />
    }),
  },
}))

function ControlledSheet({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState(true)
  return (
    <Sheet
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen)
        if (!nextOpen) {
          onClose()
        }
      }}
    >
      <SheetContent>
        <SheetTitle>Test sheet</SheetTitle>
        <SheetDescription>Regression fixture</SheetDescription>
        <SheetClose />
      </SheetContent>
    </Sheet>
  )
}

describe('SheetClose', () => {
  it('delegates one close transition to Radix', () => {
    const onClose = vi.fn()
    render(<ControlledSheet onClose={onClose} />)

    fireEvent.click(screen.getByRole('button', { name: 'Close' }))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
