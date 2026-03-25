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
          'w-full px-3 py-2 rounded-lg mono text-sm',
          'bg-slate-950/60 border border-slate-700/80 shadow-inner shadow-black/20',
          'text-slate-200 placeholder-slate-600',
          'hover:border-slate-600 hover:bg-slate-900/60',
          'focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/25 focus-visible:bg-slate-900/80 focus-visible:shadow-[0_0_16px_-4px_rgba(0,245,255,0.18)]',
          'transition-all duration-200',
          'resize-none',
          'disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-slate-700/80 disabled:hover:bg-slate-950/60',
          className,
        )}
        {...props}
      />
    )
  },
)

Textarea.displayName = 'Textarea'
