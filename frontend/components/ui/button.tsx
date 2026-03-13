'use client'

import { clsx } from 'clsx'
import { type ButtonHTMLAttributes, forwardRef, type ReactNode } from 'react'

type ButtonVariant =
  | 'primary'
  | 'secondary'
  | 'ghost'
  | 'outline'
  | 'destructive'
type ButtonSize = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  children: ReactNode
  asChild?: boolean
}

const variants: Record<ButtonVariant, string> = {
  primary: `
    bg-outrun-600 text-white border border-outrun-500
    hover:bg-outrun-500 hover:shadow-lg hover:shadow-outrun-500/20
    active:bg-outrun-700
    disabled:bg-slate-700 disabled:border-slate-600 disabled:text-slate-500
  `,
  secondary: `
    bg-slate-800 text-slate-200 border border-slate-700
    hover:bg-slate-750 hover:border-slate-600
    active:bg-slate-850
    disabled:bg-slate-850 disabled:text-slate-600
  `,
  ghost: `
    bg-transparent text-slate-400
    hover:text-phosphor-400 hover:bg-slate-800/50
    active:bg-slate-800
    disabled:text-slate-600
  `,
  outline: `
    bg-transparent text-slate-300 border border-slate-600
    hover:border-phosphor-500/50 hover:text-phosphor-400
    active:bg-slate-800/50
    disabled:border-slate-700 disabled:text-slate-600
  `,
  destructive: `
    bg-rose-600/20 text-rose-400 border border-rose-500/30
    hover:bg-rose-600/30 hover:border-rose-500/50
    active:bg-rose-600/40
    disabled:bg-slate-800 disabled:border-slate-700 disabled:text-slate-600
  `,
}

const sizes: Record<ButtonSize, string> = {
  sm: 'px-3 py-1.5 text-xs gap-1.5',
  md: 'px-4 py-2 text-sm gap-2',
  lg: 'px-5 py-2.5 text-base gap-2',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'secondary',
      size = 'md',
      className,
      children,
      disabled,
      ...props
    },
    ref,
  ) => {
    return (
      <button
        ref={ref}
        disabled={disabled}
        className={clsx(
          'inline-flex items-center justify-center font-medium rounded-md',
          'transition-all duration-200 ease-out',
          'focus:outline-none focus:ring-2 focus:ring-outrun-500/30 focus:ring-offset-2 focus:ring-offset-slate-900',
          'disabled:cursor-not-allowed',
          variants[variant],
          sizes[size],
          className,
        )}
        {...props}
      >
        {children}
      </button>
    )
  },
)

Button.displayName = 'Button'
