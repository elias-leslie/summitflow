'use client'

import { clsx } from 'clsx'
import { Check } from 'lucide-react'
import { forwardRef, type InputHTMLAttributes } from 'react'

interface CheckboxProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'onChange'> {
  checked?: boolean
  onCheckedChange?: (checked: boolean) => void
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  ({ checked, onCheckedChange, className, disabled, ...props }, ref) => {
    return (
      <button
        type="button"
        role="checkbox"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onCheckedChange?.(!checked)}
        className={clsx(
          'w-4 h-4 rounded border flex items-center justify-center transition-all',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/30 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900',
          checked
            ? 'bg-phosphor-600 border-phosphor-500'
            : 'bg-slate-900 border-slate-600 hover:border-slate-500',
          disabled && 'opacity-50 cursor-not-allowed',
          className,
        )}
      >
        {checked && <Check className="w-3 h-3 text-white" />}
        <input
          ref={ref}
          type="checkbox"
          checked={checked}
          onChange={(e) => onCheckedChange?.(e.target.checked)}
          className="sr-only"
          {...props}
        />
      </button>
    )
  },
)

Checkbox.displayName = 'Checkbox'
