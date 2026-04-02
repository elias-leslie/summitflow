'use client'

import { clsx } from 'clsx'
import { Check, ChevronDown } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import {
  createContext,
  type ButtonHTMLAttributes,
  type ReactNode,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react'

interface SelectContextValue {
  value: string
  onChange: (value: string) => void
  open: boolean
  setOpen: (open: boolean) => void
}

const SelectContext = createContext<SelectContextValue | null>(null)

function useSelect() {
  const ctx = useContext(SelectContext)
  if (!ctx) throw new Error('Select components must be used within Select')
  return ctx
}

interface SelectProps {
  value: string
  onValueChange: (value: string) => void
  children: ReactNode
  disabled?: boolean
}

export function Select({
  value,
  onValueChange,
  children,
  disabled = false,
}: SelectProps) {
  const [open, setOpen] = useState(false)

  return (
    <SelectContext.Provider
      value={{
        value,
        onChange: onValueChange,
        open,
        setOpen: disabled ? () => {} : setOpen,
      }}
    >
      <div
        className={clsx(
          'relative',
          disabled && 'opacity-50 pointer-events-none',
        )}
      >
        {children}
      </div>
    </SelectContext.Provider>
  )
}

interface SelectTriggerProps {
  children: ReactNode
  className?: string
}

export function SelectTrigger({
  children,
  className,
  ...props
}: SelectTriggerProps & ButtonHTMLAttributes<HTMLButtonElement>) {
  const { open, setOpen } = useSelect()
  const triggerRef = useRef<HTMLButtonElement>(null)

  return (
    <button
      ref={triggerRef}
      type="button"
      onClick={() => setOpen(!open)}
      {...props}
      className={clsx(
        'flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-sm',
        'bg-slate-950/60 border border-slate-700/80 shadow-inner shadow-black/20',
        'text-slate-200 hover:border-slate-600 hover:bg-slate-900/60',
        'focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/25 focus-visible:shadow-[0_0_16px_-4px_rgba(0,245,255,0.18)]',
        'transition-all duration-200',
        className,
      )}
    >
      {children}
      <ChevronDown
        className={clsx(
          'w-4 h-4 text-slate-500 transition-transform',
          open && 'rotate-180',
        )}
      />
    </button>
  )
}

interface SelectValueProps {
  placeholder?: string
  children?: ReactNode
}

export function SelectValue({ placeholder, children }: SelectValueProps) {
  const { value } = useSelect()
  // If children provided, use them as display; otherwise show value or placeholder
  const displayValue = children ?? value
  return (
    <span className={!value ? 'text-slate-500' : ''}>
      {displayValue || placeholder}
    </span>
  )
}

interface SelectContentProps {
  children: ReactNode
  className?: string
}

export function SelectContent({ children, className }: SelectContentProps) {
  const { open, setOpen } = useSelect()
  const contentRef = useRef<HTMLDivElement>(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return

    function handleClick(e: MouseEvent) {
      if (
        contentRef.current &&
        !contentRef.current.contains(e.target as Node)
      ) {
        setOpen(false)
      }
    }

    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open, setOpen])

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          ref={contentRef}
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.15 }}
          className={clsx(
            'absolute z-50 mt-1.5 min-w-full',
            'bg-[linear-gradient(180deg,rgba(18,12,28,0.98),rgba(9,7,16,0.97))] backdrop-blur-md border border-slate-700/80 rounded-xl shadow-[0_24px_48px_-12px_rgba(0,0,0,0.75),0_0_0_1px_rgba(255,0,102,0.04)]',
            'max-h-64 overflow-auto',
            className,
          )}
        >
          <div className="p-1">{children}</div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

interface SelectItemProps {
  value: string
  children: ReactNode
  className?: string
}

export function SelectItem({ value, children, className }: SelectItemProps) {
  const { value: selected, onChange, setOpen } = useSelect()
  const isSelected = value === selected

  return (
    <button
      type="button"
      onClick={() => {
        onChange(value)
        setOpen(false)
      }}
      className={clsx(
        'flex items-center justify-between gap-2 w-full px-2 py-1.5 text-sm rounded',
        'text-left transition-colors',
        isSelected
          ? 'bg-phosphor-500/10 text-phosphor-400'
          : 'text-slate-300 hover:bg-slate-800/50',
        className,
      )}
    >
      {children}
      {isSelected && <Check className="w-4 h-4" />}
    </button>
  )
}
