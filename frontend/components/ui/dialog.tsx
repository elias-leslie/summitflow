'use client'

import clsx from 'clsx'
import { X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { type ReactNode, useCallback, useEffect } from 'react'

interface DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: ReactNode
}

interface DialogContentProps {
  children: ReactNode
  className?: string
}

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

export function Dialog({ open, onOpenChange, children }: DialogProps) {
  const handleEscape = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onOpenChange(false)
    },
    [onOpenChange],
  )

  useEffect(() => {
    if (open) {
      document.addEventListener('keydown', handleEscape)
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.removeEventListener('keydown', handleEscape)
      document.body.style.overflow = ''
    }
  }, [open, handleEscape])

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop with scanline effect */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-50 bg-slate-950/90 backdrop-blur-sm"
            onClick={() => onOpenChange(false)}
          />
          {children}
        </>
      )}
    </AnimatePresence>
  )
}

export function DialogContent({
  children,
  className = '',
}: DialogContentProps) {
  return (
    <motion.div
      role="dialog"
      aria-modal="true"
      initial={{ opacity: 0, scale: 0.95, x: '-50%', y: 'calc(-50% + 10px)' }}
      animate={{ opacity: 1, scale: 1, x: '-50%', y: '-50%' }}
      exit={{ opacity: 0, scale: 0.95, x: '-50%', y: 'calc(-50% + 10px)' }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
      className={clsx(
        'fixed left-1/2 top-1/2 z-50 bg-[linear-gradient(180deg,rgba(18,12,28,0.99),rgba(9,7,16,0.98))] border border-slate-700/80 rounded-2xl shadow-[0_32px_80px_-16px_rgba(0,0,0,0.85),0_0_0_1px_rgba(255,0,102,0.06)]',
        className,
      )}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </motion.div>
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
    <h2
      className={clsx(
        'display text-lg font-semibold text-slate-100',
        className,
      )}
    >
      {children}
    </h2>
  )
}

export function DialogDescription({
  children,
  className = '',
}: DialogDescriptionProps) {
  return (
    <p className={clsx('text-sm text-slate-400 mt-1', className)}>{children}</p>
  )
}

interface DialogCloseProps {
  onClose: () => void
  className?: string
}

export function DialogClose({ onClose, className = '' }: DialogCloseProps) {
  return (
    <button
      onClick={onClose}
      aria-label="Close dialog"
      className={clsx(
        'absolute right-4 top-4 p-1.5 rounded-lg text-slate-500 hover:text-slate-200 hover:bg-slate-800/80 transition-all duration-150',
        className,
      )}
    >
      <X className="w-4 h-4" />
    </button>
  )
}
