'use client'

import { useQueryClient } from '@tanstack/react-query'
import {
  ClipboardCopy,
  Copy,
  Download,
  Edit3,
  FileText,
  Trash2,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import {
  deletePath,
  type FileBrowserScope,
  fetchFileContent,
  getFileDownloadUrl,
  renamePath,
} from '@/lib/api/files'
import { fileQueryKeys } from '@/lib/hooks/useFileExplorer'
import { cn, getErrorMessage } from '@/lib/utils'

export interface ContextMenuPosition {
  x: number
  y: number
}

export interface FileContextMenuTarget {
  path: string
  absolutePath: string
  name: string
  isDirectory: boolean
  scope: FileBrowserScope
}

interface FileContextMenuProps {
  position: ContextMenuPosition | null
  target: FileContextMenuTarget | null
  onClose: () => void
  onMutated?: () => void
}

async function copyText(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(`Copied ${label}`)
  } catch (error) {
    toast.error(getErrorMessage(error, `Failed to copy ${label}`))
  }
}

function triggerDownload(url: string, filename: string) {
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

export function FileContextMenu({
  position,
  target,
  onClose,
  onMutated,
}: FileContextMenuProps) {
  const queryClient = useQueryClient()
  const menuRef = useRef<HTMLDivElement>(null)
  const [copyingContents, setCopyingContents] = useState(false)
  const [mutating, setMutating] = useState(false)

  useEffect(() => {
    if (!position) return

    function handleClick(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        onClose()
      }
    }

    function handleKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }

    document.addEventListener('mousedown', handleClick)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleClick)
      document.removeEventListener('keydown', handleKey)
    }
  }, [position, onClose])

  const adjustedPosition = useAdjustedPosition(menuRef, position)

  const handleCopyPath = useCallback(async () => {
    if (!target) return
    await copyText(target.absolutePath, 'path')
    onClose()
  }, [onClose, target])

  const handleCopyName = useCallback(async () => {
    if (!target) return
    await copyText(target.name, 'name')
    onClose()
  }, [onClose, target])

  const handleCopyContents = useCallback(async () => {
    if (!target || target.isDirectory) return
    setCopyingContents(true)
    try {
      const data = await fetchFileContent(target.scope, target.path)
      if (data.is_binary) {
        toast.error('Cannot copy binary file contents')
      } else if (data.content) {
        await copyText(data.content, 'file contents')
      } else {
        toast.error('File has no content')
      }
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to fetch file contents'))
    } finally {
      setCopyingContents(false)
      onClose()
    }
  }, [onClose, target])

  const handleDownload = useCallback(() => {
    if (!target || target.isDirectory) return
    triggerDownload(getFileDownloadUrl(target.scope, target.path), target.name)
    onClose()
  }, [onClose, target])

  const handleRename = useCallback(async () => {
    if (!target || mutating) return
    const nextName = window.prompt('Rename', target.name)?.trim()
    if (!nextName || nextName === target.name) {
      onClose()
      return
    }

    setMutating(true)
    try {
      await renamePath(target.scope, target.path, nextName)
      await queryClient.invalidateQueries({
        queryKey: fileQueryKeys.scope(target.scope),
      })
      toast.success(`Renamed ${target.name}`)
      onMutated?.()
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to rename path'))
    } finally {
      setMutating(false)
      onClose()
    }
  }, [mutating, onClose, onMutated, queryClient, target])

  const handleDelete = useCallback(async () => {
    if (!target || mutating) return
    if (!window.confirm(`Delete ${target.name}?`)) {
      onClose()
      return
    }

    setMutating(true)
    try {
      await deletePath(target.scope, target.path)
      await queryClient.invalidateQueries({
        queryKey: fileQueryKeys.scope(target.scope),
      })
      toast.success(`Deleted ${target.name}`)
      onMutated?.()
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to delete path'))
    } finally {
      setMutating(false)
      onClose()
    }
  }, [mutating, onClose, onMutated, queryClient, target])

  if (!position || !target) return null

  return (
    <div
      ref={menuRef}
      className={cn(
        'fixed z-50 min-w-[180px] rounded-lg border border-slate-700/80 bg-slate-900/95 py-1 shadow-xl shadow-black/40 backdrop-blur-sm',
        'animate-in fade-in-0 zoom-in-95',
      )}
      style={{ left: adjustedPosition.x, top: adjustedPosition.y }}
      role="menu"
    >
      <ContextMenuItem icon={Copy} label="Copy Path" onClick={handleCopyPath} />
      <ContextMenuItem
        icon={FileText}
        label="Copy Name"
        onClick={handleCopyName}
      />
      {!target.isDirectory ? (
        <>
          <ContextMenuItem
            icon={Download}
            label="Download"
            onClick={handleDownload}
          />
          <ContextMenuItem
            icon={ClipboardCopy}
            label={copyingContents ? 'Copying...' : 'Copy Contents'}
            onClick={handleCopyContents}
            disabled={copyingContents}
          />
        </>
      ) : null}
      <ContextMenuItem
        icon={Edit3}
        label={mutating ? 'Working...' : 'Rename'}
        onClick={handleRename}
        disabled={mutating}
      />
      <ContextMenuItem
        icon={Trash2}
        label={mutating ? 'Working...' : 'Delete'}
        onClick={handleDelete}
        disabled={mutating}
        danger
      />
    </div>
  )
}

interface ContextMenuItemProps {
  icon: React.ComponentType<{ className?: string }>
  label: string
  onClick: () => void
  disabled?: boolean
  danger?: boolean
}

function ContextMenuItem({
  icon: Icon,
  label,
  onClick,
  disabled,
  danger,
}: ContextMenuItemProps) {
  return (
    <button
      type="button"
      role="menuitem"
      className={cn(
        'flex w-full items-center gap-2.5 px-3 py-1.5 text-sm text-slate-300 transition-colors',
        'hover:bg-slate-800 hover:text-slate-100',
        danger && 'text-rose-300 hover:text-rose-200',
        disabled && 'pointer-events-none opacity-50',
      )}
      onClick={onClick}
      disabled={disabled}
    >
      <Icon
        className={cn('h-3.5 w-3.5 text-slate-500', danger && 'text-rose-400')}
      />
      {label}
    </button>
  )
}

function useAdjustedPosition(
  ref: React.RefObject<HTMLDivElement | null>,
  position: ContextMenuPosition | null,
): ContextMenuPosition {
  const [adjusted, setAdjusted] = useState<ContextMenuPosition>({ x: 0, y: 0 })

  useEffect(() => {
    if (!position) return
    let { x, y } = position

    requestAnimationFrame(() => {
      const element = ref.current
      if (!element) {
        setAdjusted({ x, y })
        return
      }
      const rect = element.getBoundingClientRect()
      if (x + rect.width > window.innerWidth)
        x = window.innerWidth - rect.width - 8
      if (y + rect.height > window.innerHeight)
        y = window.innerHeight - rect.height - 8
      setAdjusted({ x: Math.max(0, x), y: Math.max(0, y) })
    })
  }, [position, ref])

  return adjusted
}
