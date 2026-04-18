'use client'

import { useQueryClient } from '@tanstack/react-query'
import { FolderOpen, FolderTree, Upload } from 'lucide-react'
import { useCallback, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import {
  type FileBrowserScope,
  type FileTreeEntry,
  uploadFile,
} from '@/lib/api/files'
import { fileQueryKeys } from '@/lib/hooks/useFileExplorer'
import { getErrorMessage } from '@/lib/utils'
import { FileBreadcrumb } from './FileBreadcrumb'
import { FileTree } from './FileTree'
import { FileViewer } from './FileViewer'

const MIN_SIDEBAR_WIDTH = 200
const MAX_SIDEBAR_WIDTH = 500
const DEFAULT_SIDEBAR_WIDTH = 280

interface FilesWorkspaceProps {
  scope: FileBrowserScope
  title: string
  rootLabel: string
  rootHref: string
  emptyTitle: string
  emptyBody: string
}

interface FileSelection {
  path: string
  name: string
  isDirectory: boolean
}

function getParentDirectory(path: string): string {
  const lastSlash = path.lastIndexOf('/')
  return lastSlash === -1 ? '' : path.slice(0, lastSlash)
}

function getUploadDirectory(selection: FileSelection | null): string {
  if (!selection) return ''
  return selection.isDirectory
    ? selection.path
    : getParentDirectory(selection.path)
}

function formatUploadTarget(directoryPath: string): string {
  return directoryPath || 'root'
}

export function FilesWorkspace({
  scope,
  title,
  rootLabel,
  rootHref,
  emptyTitle,
  emptyBody,
}: FilesWorkspaceProps): React.ReactElement {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dragState = useRef(false)

  const [selectedEntry, setSelectedEntry] = useState<FileSelection | null>(null)
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_SIDEBAR_WIDTH)
  const [isUploading, setIsUploading] = useState(false)

  const uploadDirectory = useMemo(
    () => getUploadDirectory(selectedEntry),
    [selectedEntry],
  )

  const handleMouseDown = useCallback((event: React.MouseEvent) => {
    event.preventDefault()
    dragState.current = true

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!dragState.current) return
      const newWidth = Math.min(
        MAX_SIDEBAR_WIDTH,
        Math.max(MIN_SIDEBAR_WIDTH, moveEvent.clientX),
      )
      setSidebarWidth(newWidth)
    }

    const handleMouseUp = () => {
      dragState.current = false
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }, [])

  const handleSelectEntry = useCallback((entry: FileTreeEntry) => {
    setSelectedEntry({
      path: entry.path,
      name: entry.name,
      isDirectory: entry.is_directory,
    })
  }, [])

  const handleStartUpload = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleUploadChange = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.target.files ?? [])
      if (!files.length) return

      setIsUploading(true)
      try {
        for (const file of files) {
          await uploadFile(scope, uploadDirectory, file)
        }
        await queryClient.invalidateQueries({
          queryKey: fileQueryKeys.scope(scope),
        })
        toast.success(
          files.length === 1
            ? `Uploaded ${files[0].name}`
            : `Uploaded ${files.length} files`,
        )
      } catch (error) {
        toast.error(getErrorMessage(error, 'Failed to upload file'))
      } finally {
        event.target.value = ''
        setIsUploading(false)
      }
    },
    [queryClient, scope, uploadDirectory],
  )

  const HeaderIcon = scope.kind === 'workspace' ? FolderTree : FolderOpen
  const isViewingFile = selectedEntry && !selectedEntry.isDirectory

  return (
    <div className="flex h-full flex-col">
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={handleUploadChange}
      />

      <div className="flex items-center gap-4 border-b border-slate-800 px-6 py-4">
        <HeaderIcon className="h-5 w-5 text-emerald-400" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3">
            <h1 className="display text-lg font-semibold text-slate-100">
              {title}
            </h1>
            {selectedEntry ? (
              <FileBreadcrumb
                rootLabel={rootLabel}
                rootHref={rootHref}
                filePath={selectedEntry.path}
                className="min-w-0"
              />
            ) : null}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Upload target:{' '}
            <span className="font-mono text-slate-400">
              {formatUploadTarget(uploadDirectory)}
            </span>
          </p>
        </div>
        <button
          type="button"
          onClick={handleStartUpload}
          disabled={isUploading}
          className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs font-medium text-emerald-300 transition-colors hover:bg-emerald-500/15 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Upload className="h-3.5 w-3.5" />
          {isUploading ? 'Uploading...' : 'Upload Files'}
        </button>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div
          className="flex-shrink-0 overflow-y-auto border-r border-slate-800 bg-slate-950/50"
          style={{ width: sidebarWidth }}
        >
          <FileTree
            scope={scope}
            selectedPath={selectedEntry?.path ?? null}
            onSelect={handleSelectEntry}
          />
        </div>

        <div
          className="w-1 cursor-col-resize bg-slate-800 transition-colors hover:bg-emerald-500/30"
          onMouseDown={handleMouseDown}
        />

        <div className="flex-1 overflow-hidden">
          {isViewingFile ? (
            <FileViewer scope={scope} filePath={selectedEntry.path} />
          ) : selectedEntry ? (
            <DirectoryEmptyState
              directoryName={selectedEntry.name}
              directoryPath={selectedEntry.path}
              isUploading={isUploading}
              onUpload={handleStartUpload}
            />
          ) : (
            <BrowserEmptyState title={emptyTitle} body={emptyBody} />
          )}
        </div>
      </div>
    </div>
  )
}

function BrowserEmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="max-w-xs text-center animate-in stagger-1">
        <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-emerald-500/15 bg-emerald-500/8">
          <FolderOpen className="h-8 w-8 text-emerald-500/60" />
        </div>
        <p className="mb-1.5 text-sm font-medium text-slate-300">{title}</p>
        <p className="text-xs leading-relaxed text-slate-500">{body}</p>
        <div className="mt-5 flex items-center justify-center gap-4 text-2xs text-slate-600">
          <span className="flex items-center gap-1.5">
            <kbd className="rounded border border-slate-700 bg-slate-800 px-1.5 py-0.5 font-mono text-slate-400">
              Click
            </kbd>
            to open
          </span>
          <span className="text-slate-700">|</span>
          <span className="flex items-center gap-1.5">Drag edge to resize</span>
        </div>
      </div>
    </div>
  )
}

function DirectoryEmptyState({
  directoryName,
  directoryPath,
  isUploading,
  onUpload,
}: {
  directoryName: string
  directoryPath: string
  isUploading: boolean
  onUpload: () => void
}) {
  return (
    <div className="flex h-full items-center justify-center px-6">
      <div className="max-w-md rounded-3xl border border-slate-800 bg-slate-950/55 p-8 text-center shadow-[0_28px_70px_-52px_rgba(0,0,0,0.95)]">
        <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl border border-emerald-500/15 bg-emerald-500/8">
          <FolderOpen className="h-7 w-7 text-emerald-400/70" />
        </div>
        <h2 className="display text-lg font-semibold text-slate-100">
          {directoryName}
        </h2>
        <p className="mt-2 break-all font-mono text-xs text-slate-500">
          {directoryPath || 'root'}
        </p>
        <p className="mt-4 text-sm leading-relaxed text-slate-400">
          Directory selected. Upload files here or pick a file from the tree to
          preview and download it.
        </p>
        <button
          type="button"
          onClick={onUpload}
          disabled={isUploading}
          className="mt-6 inline-flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-4 py-2 text-sm font-medium text-emerald-300 transition-colors hover:bg-emerald-500/15 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Upload className="h-4 w-4" />
          {isUploading ? 'Uploading...' : 'Upload Into Directory'}
        </button>
      </div>
    </div>
  )
}
