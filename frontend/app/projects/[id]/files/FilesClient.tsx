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
        <h1 className="text-lg font-semibold text-slate-100">Files</h1>
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
            <div className="flex h-full items-center justify-center text-slate-500">
              <div className="text-center">
                <FolderOpen className="mx-auto mb-3 h-12 w-12 text-slate-700" />
                <p className="text-sm">Select a file to view</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
