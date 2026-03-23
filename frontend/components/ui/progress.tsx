'use client'

import * as ProgressPrimitive from '@radix-ui/react-progress'
import type * as React from 'react'

import { cn } from '@/lib/utils'

function Progress({
  className,
  value,
  ...props
}: React.ComponentProps<typeof ProgressPrimitive.Root>) {
  const hasValue = (value || 0) > 0
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      className={cn(
        'bg-slate-800/60 ring-1 ring-white/5 relative h-2 w-full overflow-hidden rounded-full',
        className,
      )}
      {...props}
    >
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        className={cn(
          'h-full w-full flex-1 transition-all duration-500 ease-out',
          hasValue ? 'bg-phosphor-500 shadow-[0_0_8px_rgba(0,245,255,0.3)]' : 'bg-phosphor-500',
        )}
        style={{ transform: `translateX(-${100 - (value || 0)}%)` }}
      />
    </ProgressPrimitive.Root>
  )
}

export { Progress }
