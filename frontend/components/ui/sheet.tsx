'use client'

import { X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { type ReactNode, useCallback, useEffect } from 'react'

interface SheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: ReactNode
}

interface SheetContentProps {
  children: ReactNode
  className?: string
  side?: 'left' | 'right'
}

interface SheetHeaderProps {
  children: ReactNode
  className?: string
}

interface SheetTitleProps {
  children: ReactNode
  className?: string
}

interface SheetDescriptionProps {
  children: ReactNode
  className?: string
}

export function Sheet({ open, onOpenChange, children }: SheetProps) {
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
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm"
            onClick={() => onOpenChange(false)}
          />
          {children}
        </>
      )}
    </AnimatePresence>
  )
}

export function SheetContent({
  children,
  className = '',
  side = 'right',
}: SheetContentProps) {
  const isRight = side === 'right'

  return (
    <motion.div
      initial={{ x: isRight ? '100%' : '-100%' }}
      animate={{ x: 0 }}
      exit={{ x: isRight ? '100%' : '-100%' }}
      transition={{ duration: 0.3, ease: [0.32, 0.72, 0, 1] }}
      className={`fixed ${isRight ? 'right-0' : 'left-0'} top-0 bottom-0 z-50
        w-full max-w-md bg-slate-900 border-l border-slate-700 shadow-2xl
        shadow-phosphor-500/5 overflow-y-auto ${className}`}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </motion.div>
  )
}

export function SheetHeader({ children, className = '' }: SheetHeaderProps) {
  return (
    <div
      className={`sticky top-0 bg-slate-900/95 backdrop-blur border-b border-slate-700 px-5 py-4 ${className}`}
    >
      {children}
    </div>
  )
}

export function SheetTitle({ children, className = '' }: SheetTitleProps) {
  return (
    <h2 className={`display text-lg font-semibold text-white ${className}`}>
      {children}
    </h2>
  )
}

export function SheetDescription({
  children,
  className = '',
}: SheetDescriptionProps) {
  return (
    <p className={`text-sm text-slate-400 mt-1 ${className}`}>{children}</p>
  )
}

interface SheetCloseProps {
  onClose: () => void
  className?: string
}

export function SheetClose({ onClose, className = '' }: SheetCloseProps) {
  return (
    <button
      onClick={onClose}
      aria-label="Close"
      className={`absolute right-4 top-4 p-1.5 rounded-md text-slate-500
        hover:text-phosphor-400 hover:bg-slate-800 transition-colors ${className}`}
    >
      <X className="w-4 h-4" />
    </button>
  )
}

export function SheetBody({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return <div className={`px-5 py-4 ${className}`}>{children}</div>
}
