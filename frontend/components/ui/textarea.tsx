'use client'

import { clsx } from 'clsx'
import { forwardRef, type TextareaHTMLAttributes } from 'react'

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        className={clsx(
          'w-full px-3 py-2 rounded-md mono text-sm',
          'bg-slate-900/80 border border-slate-700',
          'text-slate-200 placeholder-slate-500',
          'focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20 focus-visible:bg-slate-900',
          'transition-all duration-200',
          'resize-none',
          'disabled:opacity-50 disabled:cursor-not-allowed',
          className,
        )}
        {...props}
      />
    )
  },
)

Textarea.displayName = 'Textarea'
