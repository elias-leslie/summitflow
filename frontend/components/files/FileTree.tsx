'use client'

import { useCallback, useState } from 'react'
import {
  ChevronRight,
  File,
  FileCode,
  FileJson,
  FileText,
  Folder,
  FolderOpen,
  Loader2,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useFileTree } from '@/lib/hooks/useFileExplorer'
import type { FileTreeEntry } from '@/lib/api/files'
import { FileContextMenu } from './FileContextMenu'
import type { ContextMenuPosition, FileContextMenuTarget } from './FileContextMenu'

// ============================================================================
// File icon mapping
// ============================================================================

const CODE_EXTENSIONS = new Set([
  '.ts', '.tsx', '.js', '.jsx', '.py', '.rs', '.go', '.java',
  '.cpp', '.c', '.h', '.hpp', '.php', '.rb', '.swift', '.kt',
  '.sh', '.bash', '.zsh', '.css', '.scss', '.html', '.htm',
  '.xml', '.sql',
])

const JSON_EXTENSIONS = new Set(['.json', '.jsonc', '.json5'])
const TEXT_EXTENSIONS = new Set(['.md', '.mdx', '.yaml', '.yml', '.txt', '.toml', '.ini', '.cfg', '.env'])

function getFileIcon(entry: FileTreeEntry) {
  if (entry.is_directory) return null // Handled separately
  const ext = entry.extension?.toLowerCase()
  if (ext && CODE_EXTENSIONS.has(ext)) return FileCode
  if (ext && JSON_EXTENSIONS.has(ext)) return FileJson
  if (ext && TEXT_EXTENSIONS.has(ext)) return FileText
  return File
}

// ============================================================================
// TreeNode Component
// ============================================================================

interface TreeNodeProps {
  entry: FileTreeEntry
  projectId: string
  depth: number
  selectedFile: string | null
  onSelect: (path: string) => void
  onContextMenu: (e: React.MouseEvent, entry: FileTreeEntry) => void
}

function TreeNode({ entry, projectId, depth, selectedFile, onSelect, onContextMenu }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(false)
  const isSelected = selectedFile === entry.path

  const { data, isLoading } = useFileTree(
    projectId,
    expanded ? entry.path : '',
  )

  const handleClick = useCallback(() => {
    if (entry.is_directory) {
      setExpanded(prev => !prev)
    } else {
      onSelect(entry.path)
    }
  }, [entry.is_directory, entry.path, onSelect])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      handleClick()
    } else if (e.key === 'ArrowRight' && entry.is_directory && !expanded) {
      e.preventDefault()
      setExpanded(true)
    } else if (e.key === 'ArrowLeft' && entry.is_directory && expanded) {
      e.preventDefault()
      setExpanded(false)
    }
  }, [entry.is_directory, expanded, handleClick])

  const paddingLeft = 12 + depth * 16
  const FileIcon = getFileIcon(entry)

  return (
    <li role="treeitem" tabIndex={-1} aria-expanded={entry.is_directory ? expanded : undefined} aria-selected={isSelected}>
      <button
        type="button"
        className={cn(
          'flex w-full items-center gap-1.5 py-1 pr-3 text-left text-sm transition-colors',
          'hover:bg-slate-800/50',
          isSelected && 'bg-emerald-500/10 text-emerald-400',
          !isSelected && 'text-slate-300',
        )}
        style={{ paddingLeft }}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        onContextMenu={(e) => onContextMenu(e, entry)}
      >
        {/* Expand chevron for directories */}
        {entry.is_directory ? (
          <ChevronRight
            className={cn(
              'h-3.5 w-3.5 flex-shrink-0 text-slate-500 transition-transform',
              expanded && 'rotate-90',
            )}
          />
        ) : (
          <span className="w-3.5 flex-shrink-0" />
        )}

        {/* Icon */}
        {entry.is_directory ? (
          expanded ? (
            <FolderOpen className="h-4 w-4 flex-shrink-0 text-emerald-400/70" />
          ) : (
            <Folder className="h-4 w-4 flex-shrink-0 text-slate-500" />
          )
        ) : (
          FileIcon && <FileIcon className={cn('h-4 w-4 flex-shrink-0', isSelected ? 'text-emerald-400' : 'text-slate-500')} />
        )}

        {/* Name */}
        <span className="truncate">{entry.name}</span>
      </button>

      {/* Children */}
      {entry.is_directory && expanded && (
        <ul role="group">
          {isLoading ? (
            <li className="flex items-center gap-2 py-1 text-xs text-slate-500" style={{ paddingLeft: paddingLeft + 20 }}>
              <Loader2 className="h-3 w-3 animate-spin" />
              Loading...
            </li>
          ) : (
            data?.entries.map(child => (
              <TreeNode
                key={child.path}
                entry={child}
                projectId={projectId}
                depth={depth + 1}
                selectedFile={selectedFile}
                onSelect={onSelect}
                onContextMenu={onContextMenu}
              />
            ))
          )}
        </ul>
      )}
    </li>
  )
}

// ============================================================================
// FileTree Component
// ============================================================================

interface FileTreeProps {
  projectId: string
  selectedFile: string | null
  onSelect: (path: string) => void
}

export function FileTree({ projectId, selectedFile, onSelect }: FileTreeProps) {
  const { data, isLoading, isError, error } = useFileTree(projectId, '')
  const [menuPosition, setMenuPosition] = useState<ContextMenuPosition | null>(null)
  const [menuTarget, setMenuTarget] = useState<FileContextMenuTarget | null>(null)

  const handleContextMenu = useCallback((e: React.MouseEvent, entry: FileTreeEntry) => {
    e.preventDefault()
    setMenuPosition({ x: e.clientX, y: e.clientY })
    setMenuTarget({
      path: entry.path,
      name: entry.name,
      isDirectory: entry.is_directory,
      projectId,
    })
  }, [projectId])

  const handleCloseMenu = useCallback(() => {
    setMenuPosition(null)
    setMenuTarget(null)
  }, [])

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 p-4 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading files...
      </div>
    )
  }

  if (isError) {
    return (
      <div className="p-4 text-sm text-red-400">
        Failed to load files: {error?.message ?? 'Unknown error'}
      </div>
    )
  }

  if (!data?.entries.length) {
    return (
      <div className="p-4 text-sm text-slate-500">No files found</div>
    )
  }

  return (
    <>
      <div role="tree" className="py-2">
        {data.entries.map(entry => (
          <TreeNode
            key={entry.path}
            entry={entry}
            projectId={projectId}
            depth={0}
            selectedFile={selectedFile}
            onSelect={onSelect}
            onContextMenu={handleContextMenu}
          />
        ))}
      </div>
      <FileContextMenu
        position={menuPosition}
        target={menuTarget}
        onClose={handleCloseMenu}
      />
    </>
  )
}
