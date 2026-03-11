'use client'

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
      initial={{ opacity: 0, scale: 0.95, x: '-50%', y: 'calc(-50% + 10px)' }}
      animate={{ opacity: 1, scale: 1, x: '-50%', y: '-50%' }}
      exit={{ opacity: 0, scale: 0.95, x: '-50%', y: 'calc(-50% + 10px)' }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
      className={`fixed left-1/2 top-1/2 z-50
        bg-slate-900 border border-slate-700 rounded-lg shadow-2xl
        shadow-phosphor-500/5 ${className}`}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </motion.div>
  )
}

export function DialogHeader({ children, className = '' }: DialogHeaderProps) {
  return (
    <div className={`border-b border-slate-700 px-5 py-4 ${className}`}>
      {children}
    </div>
  )
}

export function DialogTitle({ children, className = '' }: DialogTitleProps) {
  return (
    <h2 className={`display text-lg font-semibold text-white ${className}`}>
      {children}
    </h2>
  )
}

export function DialogDescription({
  children,
  className = '',
}: DialogDescriptionProps) {
  return (
    <p className={`text-sm text-slate-400 mt-1 ${className}`}>{children}</p>
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
      className={`absolute right-4 top-4 p-1.5 rounded-md text-slate-500
        hover:text-phosphor-400 hover:bg-slate-800 transition-colors ${className}`}
    >
      <X className="w-4 h-4" />
    </button>
  )
}
