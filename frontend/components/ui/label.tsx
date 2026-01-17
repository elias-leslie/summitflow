'use client'

import { clsx } from 'clsx'
import { forwardRef, type LabelHTMLAttributes } from 'react'

type LabelProps = LabelHTMLAttributes<HTMLLabelElement>

export const Label = forwardRef<HTMLLabelElement, LabelProps>(
  ({ className, ...props }, ref) => {
    return (
      <label
        ref={ref}
        className={clsx(
          'text-sm font-medium text-slate-300',
          'cursor-pointer',
          className,
        )}
        {...props}
      />
    )
  },
)

Label.displayName = 'Label'
