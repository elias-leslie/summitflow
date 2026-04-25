'use client'

import {
  ArrowUp,
  ChevronRight,
  File,
  FileCode,
  FileJson,
  FileText,
  Folder,
  FolderOpen,
  Loader2,
  Server,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FileBrowserScope, FileTreeEntry } from '@/lib/api/files'
import { useFileTree } from '@/lib/hooks/useFileExplorer'
import { cn } from '@/lib/utils'
import {
  type ContextMenuPosition,
  FileContextMenu,
  type FileContextMenuTarget,
} from './FileContextMenu'

const CODE_EXTENSIONS = new Set([
  '.ts',
  '.tsx',
  '.js',
  '.jsx',
  '.py',
  '.rs',
  '.go',
  '.java',
  '.cpp',
  '.c',
  '.h',
  '.hpp',
  '.php',
  '.rb',
  '.swift',
  '.kt',
  '.sh',
  '.bash',
  '.zsh',
  '.css',
  '.scss',
  '.html',
  '.htm',
  '.xml',
  '.sql',
])

const JSON_EXTENSIONS = new Set(['.json', '.jsonc', '.json5'])
const TEXT_EXTENSIONS = new Set([
  '.md',
  '.mdx',
  '.yaml',
  '.yml',
  '.txt',
  '.toml',
  '.ini',
  '.cfg',
  '.env',
])

function getFileIcon(entry: FileTreeEntry) {
  if (entry.is_directory) return null
  const extension = entry.extension?.toLowerCase()
  if (extension && CODE_EXTENSIONS.has(extension)) return FileCode
  if (extension && JSON_EXTENSIONS.has(extension)) return FileJson
  if (extension && TEXT_EXTENSIONS.has(extension)) return FileText
  return File
}

function getParentPath(absolutePath: string): string | null {
  if (!absolutePath || absolutePath === '/') return null
  const parent = absolutePath.slice(0, absolutePath.lastIndexOf('/')) || '/'
  return parent
}

interface TreeNodeProps {
  entry: FileTreeEntry
  scope: FileBrowserScope
  depth: number
  selectedPath: string | null
  onSelect: (entry: FileTreeEntry) => void
  onContextMenu: (event: React.MouseEvent, entry: FileTreeEntry) => void
}

function TreeNode({
  entry,
  scope,
  depth,
  selectedPath,
  onSelect,
  onContextMenu,
}: TreeNodeProps) {
  const [expanded, setExpanded] = useState(false)
  const isSelected = selectedPath === entry.path

  const { data, isLoading } = useFileTree(scope, expanded ? entry.path : '')

  const handleClick = useCallback(() => {
    onSelect(entry)
    if (entry.is_directory) {
      setExpanded((current) => !current)
    }
  }, [entry, onSelect])

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        handleClick()
      } else if (
        event.key === 'ArrowRight' &&
        entry.is_directory &&
        !expanded
      ) {
        event.preventDefault()
        setExpanded(true)
        onSelect(entry)
      } else if (event.key === 'ArrowLeft' && entry.is_directory && expanded) {
        event.preventDefault()
        setExpanded(false)
        onSelect(entry)
      }
    },
    [entry, expanded, handleClick, onSelect],
  )

  const paddingLeft = 12 + depth * 16
  const FileIcon = getFileIcon(entry)

  return (
    <li
      role="treeitem"
      tabIndex={-1}
      aria-expanded={entry.is_directory ? expanded : undefined}
      aria-selected={isSelected}
    >
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
        onContextMenu={(event) => onContextMenu(event, entry)}
      >
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

        {entry.is_directory ? (
          expanded ? (
            <FolderOpen className="h-4 w-4 flex-shrink-0 text-emerald-400/70" />
          ) : (
            <Folder className="h-4 w-4 flex-shrink-0 text-slate-500" />
          )
        ) : FileIcon ? (
          <FileIcon
            className={cn(
              'h-4 w-4 flex-shrink-0',
              isSelected ? 'text-emerald-400' : 'text-slate-500',
            )}
          />
        ) : null}

        <span className="truncate">{entry.name}</span>
      </button>

      {entry.is_directory && expanded ? (
        <ul role="group">
          {isLoading ? (
            <li
              className="flex items-center gap-2 py-1 text-xs text-slate-500"
              style={{ paddingLeft: paddingLeft + 20 }}
            >
              <Loader2 className="h-3 w-3 animate-spin" />
              Loading...
            </li>
          ) : (
            data?.entries.map((child) => (
              <TreeNode
                key={child.path}
                entry={child}
                scope={scope}
                depth={depth + 1}
                selectedPath={selectedPath}
                onSelect={onSelect}
                onContextMenu={onContextMenu}
              />
            ))
          )}
        </ul>
      ) : null}
    </li>
  )
}

interface FileTreeProps {
  scope: FileBrowserScope
  rootPath?: string
  selectedPath: string | null
  onRootPathChange?: (path: string) => void
  onRootPathResolved?: (absolutePath: string) => void
  onSelect: (entry: FileTreeEntry) => void
  onMutated?: () => void
}

export function FileTree({
  scope,
  rootPath = '',
  selectedPath,
  onRootPathChange,
  onRootPathResolved,
  onSelect,
  onMutated,
}: FileTreeProps) {
  const { data, isLoading, isError, error } = useFileTree(scope, rootPath)
  const [menuPosition, setMenuPosition] = useState<ContextMenuPosition | null>(
    null,
  )
  const [menuTarget, setMenuTarget] = useState<FileContextMenuTarget | null>(
    null,
  )

  useEffect(() => {
    if (data?.absolute_path) onRootPathResolved?.(data.absolute_path)
  }, [data?.absolute_path, onRootPathResolved])

  const handleContextMenu = useCallback(
    (event: React.MouseEvent, entry: FileTreeEntry) => {
      event.preventDefault()
      setMenuPosition({ x: event.clientX, y: event.clientY })
      setMenuTarget({
        path: entry.path,
        absolutePath: entry.absolute_path,
        name: entry.name,
        isDirectory: entry.is_directory,
        scope,
      })
    },
    [scope],
  )

  const handleCloseMenu = useCallback(() => {
    setMenuPosition(null)
    setMenuTarget(null)
  }, [])

  const parentPath = useMemo(
    () => getParentPath(data?.absolute_path ?? ''),
    [data?.absolute_path],
  )

  const handleBrowse = useCallback(
    (path: string) => {
      onRootPathChange?.(path)
      handleCloseMenu()
    },
    [handleCloseMenu, onRootPathChange],
  )

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

  const displayPath = data?.absolute_path ?? '/'

  return (
    <>
      <div className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/95 px-3 py-2">
        <div className="mb-2 truncate font-mono text-xs text-slate-400">
          {displayPath}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={!parentPath}
            onClick={() => parentPath && handleBrowse(parentPath)}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-slate-700 px-2 text-xs text-slate-300 transition-colors hover:border-slate-600 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-45"
          >
            <ArrowUp className="h-3.5 w-3.5" />
            Up
          </button>
          {scope.kind === 'project' ? (
            <button
              type="button"
              onClick={() => handleBrowse('')}
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-slate-700 px-2 text-xs text-slate-300 transition-colors hover:border-slate-600 hover:bg-slate-800"
            >
              <FolderOpen className="h-3.5 w-3.5" />
              Project
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => handleBrowse(scope.kind === 'project' ? '/' : '')}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-slate-700 px-2 text-xs text-slate-300 transition-colors hover:border-slate-600 hover:bg-slate-800"
          >
            <Server className="h-3.5 w-3.5" />/
          </button>
        </div>
      </div>
      <div role="tree" className="py-2">
        {data?.entries.length ? (
          data.entries.map((entry) => (
            <TreeNode
              key={entry.path}
              entry={entry}
              scope={scope}
              depth={0}
              selectedPath={selectedPath}
              onSelect={onSelect}
              onContextMenu={handleContextMenu}
            />
          ))
        ) : (
          <div className="p-4 text-sm text-slate-500">No files found</div>
        )}
      </div>
      <FileContextMenu
        position={menuPosition}
        target={menuTarget}
        onClose={handleCloseMenu}
        onMutated={onMutated}
      />
    </>
  )
}
