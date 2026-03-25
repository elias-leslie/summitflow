'use client'

import { useParams } from 'next/navigation'
import { useCallback, useRef, useState } from 'react'
import { FolderOpen } from 'lucide-react'
import { FileTree, FileViewer, FileBreadcrumb } from '@/components/files'

const MIN_SIDEBAR_WIDTH = 200
const MAX_SIDEBAR_WIDTH = 500
const DEFAULT_SIDEBAR_WIDTH = 280

export function FilesClient(): React.ReactElement {
  const params = useParams()
  const projectId = params.id as string

  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_SIDEBAR_WIDTH)
  const isDragging = useRef(false)

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    isDragging.current = true

    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return
      const newWidth = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, e.clientX))
      setSidebarWidth(newWidth)
    }

    const handleMouseUp = () => {
      isDragging.current = false
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }, [])

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-slate-800 px-6 py-4">
        <FolderOpen className="h-5 w-5 text-emerald-400" />
        <h1 className="text-lg font-semibold text-slate-100 display">Files</h1>
        {selectedFile && (
          <FileBreadcrumb
            projectId={projectId}
            filePath={selectedFile}
            className="ml-2"
          />
        )}
      </div>

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Tree sidebar */}
        <div
          className="flex-shrink-0 overflow-y-auto border-r border-slate-800 bg-slate-950/50"
          style={{ width: sidebarWidth }}
        >
          <FileTree
            projectId={projectId}
            selectedFile={selectedFile}
            onSelect={setSelectedFile}
          />
        </div>

        {/* Resize handle */}
        <div
          className="w-1 cursor-col-resize bg-slate-800 hover:bg-emerald-500/30 transition-colors"
          onMouseDown={handleMouseDown}
        />

        {/* File viewer */}
        <div className="flex-1 overflow-hidden">
          {selectedFile ? (
            <FileViewer projectId={projectId} filePath={selectedFile} />
          ) : (
            <div className="flex h-full items-center justify-center">
              <div className="text-center max-w-xs animate-in stagger-1">
                <div className="mx-auto mb-5 w-16 h-16 rounded-2xl bg-emerald-500/8 border border-emerald-500/15 flex items-center justify-center">
                  <FolderOpen className="h-8 w-8 text-emerald-500/60" />
                </div>
                <p className="text-sm font-medium text-slate-300 mb-1.5">Browse project files</p>
                <p className="text-xs text-slate-500 leading-relaxed">
                  Select a file from the tree to view its contents, syntax-highlighted and ready to explore.
                </p>
                <div className="mt-5 flex items-center justify-center gap-4 text-2xs text-slate-600">
                  <span className="flex items-center gap-1.5">
                    <kbd className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 font-mono text-slate-400">Click</kbd>
                    to open
                  </span>
                  <span className="text-slate-700">|</span>
                  <span className="flex items-center gap-1.5">
                    Drag edge to resize
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
