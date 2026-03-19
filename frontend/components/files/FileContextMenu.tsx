'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { ClipboardCopy, Copy, FileText } from 'lucide-react'
import { toast } from 'sonner'
import { cn, getErrorMessage } from '@/lib/utils'
import { fetchFileContent } from '@/lib/api/files'

// ============================================================================
// Types
// ============================================================================

export interface ContextMenuPosition {
  x: number
  y: number
}

export interface FileContextMenuTarget {
  path: string
  name: string
  isDirectory: boolean
  projectId: string
}

interface FileContextMenuProps {
  position: ContextMenuPosition | null
  target: FileContextMenuTarget | null
  onClose: () => void
}

// ============================================================================
// Copy helpers
// ============================================================================

async function copyText(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(`Copied ${label}`)
  } catch (err) {
    toast.error(getErrorMessage(err, `Failed to copy ${label}`))
  }
}

// ============================================================================
// FileContextMenu
// ============================================================================

export function FileContextMenu({ position, target, onClose }: FileContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)
  const [copyingContents, setCopyingContents] = useState(false)

  // Close on outside click or Escape
  useEffect(() => {
    if (!position) return

    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }

    document.addEventListener('mousedown', handleClick)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleClick)
      document.removeEventListener('keydown', handleKey)
    }
  }, [position, onClose])

  // Adjust position to keep menu in viewport
  const adjustedPosition = useAdjustedPosition(menuRef, position)

  const handleCopyPath = useCallback(async () => {
    if (!target) return
    await copyText(target.path, 'path')
    onClose()
  }, [target, onClose])

  const handleCopyName = useCallback(async () => {
    if (!target) return
    await copyText(target.name, 'name')
    onClose()
  }, [target, onClose])

  const handleCopyContents = useCallback(async () => {
    if (!target || target.isDirectory) return
    setCopyingContents(true)
    try {
      const data = await fetchFileContent(target.projectId, target.path)
      if (data.is_binary) {
        toast.error('Cannot copy binary file contents')
      } else if (data.content) {
        await copyText(data.content, 'file contents')
      } else {
        toast.error('File has no content')
      }
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to fetch file contents'))
    } finally {
      setCopyingContents(false)
      onClose()
    }
  }, [target, onClose])

  if (!position || !target) return null

  return (
    <div
      ref={menuRef}
      className={cn(
        'fixed z-50 min-w-[180px] rounded-lg border border-slate-700 bg-slate-900 py-1 shadow-xl',
        'animate-in fade-in-0 zoom-in-95',
      )}
      style={{ left: adjustedPosition.x, top: adjustedPosition.y }}
      role="menu"
    >
      <ContextMenuItem icon={Copy} label="Copy Path" onClick={handleCopyPath} />
      <ContextMenuItem icon={FileText} label="Copy Name" onClick={handleCopyName} />
      {!target.isDirectory && (
        <ContextMenuItem
          icon={ClipboardCopy}
          label={copyingContents ? 'Copying...' : 'Copy Contents'}
          onClick={handleCopyContents}
          disabled={copyingContents}
        />
      )}
    </div>
  )
}

// ============================================================================
// ContextMenuItem
// ============================================================================

interface ContextMenuItemProps {
  icon: React.ComponentType<{ className?: string }>
  label: string
  onClick: () => void
  disabled?: boolean
}

function ContextMenuItem({ icon: Icon, label, onClick, disabled }: ContextMenuItemProps) {
  return (
    <button
      type="button"
      role="menuitem"
      className={cn(
        'flex w-full items-center gap-2.5 px-3 py-1.5 text-sm text-slate-300',
        'hover:bg-slate-800 hover:text-slate-100',
        'transition-colors',
        disabled && 'pointer-events-none opacity-50',
      )}
      onClick={onClick}
      disabled={disabled}
    >
      <Icon className="h-3.5 w-3.5 text-slate-500" />
      {label}
    </button>
  )
}

// ============================================================================
// Hook: keep menu within viewport
// ============================================================================

function useAdjustedPosition(
  ref: React.RefObject<HTMLDivElement | null>,
  position: ContextMenuPosition | null,
): ContextMenuPosition {
  const [adjusted, setAdjusted] = useState<ContextMenuPosition>({ x: 0, y: 0 })

  useEffect(() => {
    if (!position) return
    // Start at requested position
    let { x, y } = position

    // After render, check if the menu overflows
    requestAnimationFrame(() => {
      const el = ref.current
      if (!el) {
        setAdjusted({ x, y })
        return
      }
      const rect = el.getBoundingClientRect()
      if (x + rect.width > window.innerWidth) x = window.innerWidth - rect.width - 8
      if (y + rect.height > window.innerHeight) y = window.innerHeight - rect.height - 8
      setAdjusted({ x: Math.max(0, x), y: Math.max(0, y) })
    })
  }, [position, ref])

  return adjusted
}
