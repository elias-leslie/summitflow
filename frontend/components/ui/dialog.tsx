'use client'

import * as DialogPrimitive from '@radix-ui/react-dialog'
import clsx from 'clsx'
import { X } from 'lucide-react'
import {
  type ComponentPropsWithoutRef,
  createContext,
  type MutableRefObject,
  type ReactNode,
  useContext,
  useRef,
} from 'react'

interface DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: ReactNode
}

type DialogContentProps = ComponentPropsWithoutRef<
  typeof DialogPrimitive.Content
>

interface DialogHeaderProps {
  children: ReactNode
  className?: string
}

interface DialogTitleProps {
  children: ReactNode
  className?: string
}

interface DialogDescriptionProps {
  children: ReactNode
  className?: string
}

const DialogRestoreFocusContext = createContext<
  MutableRefObject<HTMLElement | null> | undefined
>(undefined)

/** Accessible modal root backed by Radix focus and dismissal primitives. */
export function Dialog({ open, onOpenChange, children }: DialogProps) {
  const restoreFocusRef = useRef<HTMLElement | null>(null)

  return (
    <DialogRestoreFocusContext.Provider value={restoreFocusRef}>
      <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
        {children}
      </DialogPrimitive.Root>
    </DialogRestoreFocusContext.Provider>
  )
}

export function DialogContent({
  children,
  className = '',
  onCloseAutoFocus,
  onOpenAutoFocus,
  ...props
}: DialogContentProps) {
  const restoreFocusRef = useContext(DialogRestoreFocusContext)

  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-slate-950/90 backdrop-blur-sm data-[state=closed]:animate-out data-[state=closed]:fade-out data-[state=open]:animate-in data-[state=open]:fade-in motion-reduce:animate-none" />
      <DialogPrimitive.Content
        onOpenAutoFocus={(event) => {
          if (document.activeElement instanceof HTMLElement) {
            if (restoreFocusRef) {
              restoreFocusRef.current = document.activeElement
            }
          }
          onOpenAutoFocus?.(event)
        }}
        onCloseAutoFocus={(event) => {
          onCloseAutoFocus?.(event)
          const target = restoreFocusRef?.current
          if (!event.defaultPrevented && target?.isConnected) {
            event.preventDefault()
            target.focus()
          }
        }}
        className={clsx(
          'fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-slate-700/80 bg-[linear-gradient(180deg,rgba(18,12,28,0.99),rgba(9,7,16,0.98))] shadow-[0_32px_80px_-16px_rgba(0,0,0,0.85),0_0_0_1px_rgba(255,0,102,0.06)] focus:outline-none data-[state=closed]:animate-out data-[state=closed]:fade-out data-[state=closed]:zoom-out-95 data-[state=open]:animate-in data-[state=open]:fade-in data-[state=open]:zoom-in-95 motion-reduce:animate-none',
          className,
        )}
        {...props}
      >
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}

export function DialogHeader({ children, className = '' }: DialogHeaderProps) {
  return (
    <div className={clsx('border-b border-slate-700/70 px-5 py-4', className)}>
      {children}
    </div>
  )
}

export function DialogTitle({ children, className = '' }: DialogTitleProps) {
  return (
    <DialogPrimitive.Title asChild>
      <h2
        className={clsx(
          'display text-lg font-semibold text-slate-100',
          className,
        )}
      >
        {children}
      </h2>
    </DialogPrimitive.Title>
  )
}

export function DialogDescription({
  children,
  className = '',
}: DialogDescriptionProps) {
  return (
    <DialogPrimitive.Description asChild>
      <p className={clsx('mt-1 text-sm text-slate-400', className)}>
        {children}
      </p>
    </DialogPrimitive.Description>
  )
}

type DialogCloseProps = Omit<
  ComponentPropsWithoutRef<'button'>,
  'children' | 'type'
>

export function DialogClose({ className = '', ...props }: DialogCloseProps) {
  return (
    <DialogPrimitive.Close asChild>
      <button
        type="button"
        aria-label="Close dialog"
        className={clsx(
          'absolute right-4 top-4 rounded-lg p-1.5 text-slate-500 transition-all duration-150 hover:bg-slate-800/80 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/50',
          className,
        )}
        {...props}
      >
        <X className="h-4 w-4" />
      </button>
    </DialogPrimitive.Close>
  )
}
