'use client'

import * as Dialog from '@radix-ui/react-dialog'
import clsx from 'clsx'
import {
  ChevronDown,
  ChevronRight,
  FileCode2,
  FileMinus2,
  FilePlus2,
  Minus,
  Plus,
  X,
} from 'lucide-react'
import { useState } from 'react'
import type { DiffFile, DiffStats } from '@/lib/api/git-enhanced'

interface DiffPanelProps {
  open: boolean
  onClose: () => void
  title: string
  subtitle?: string
  files: DiffFile[]
  stats: DiffStats
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'added':
      return <FilePlus2 className="w-3.5 h-3.5 text-emerald-400" />
    case 'deleted':
      return <FileMinus2 className="w-3.5 h-3.5 text-rose-400" />
    default:
      return <FileCode2 className="w-3.5 h-3.5 text-amber-400" />
  }
}

function DiffFileSection({ file }: { file: DiffFile }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="border border-slate-800 rounded-md overflow-hidden">
      {/* File header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-slate-900/60 hover:bg-slate-800/60 transition-colors text-left"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-slate-500 shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-slate-500 shrink-0" />
        )}
        <StatusIcon status={file.status} />
        <span className="text-xs font-mono text-slate-300 truncate flex-1">
          {file.path}
        </span>
        <div className="flex items-center gap-2 shrink-0">
          {file.additions > 0 && (
            <span className="text-[10px] font-mono text-emerald-400 flex items-center gap-0.5">
              <Plus className="w-2.5 h-2.5" />
              {file.additions}
            </span>
          )}
          {file.deletions > 0 && (
            <span className="text-[10px] font-mono text-rose-400 flex items-center gap-0.5">
              <Minus className="w-2.5 h-2.5" />
              {file.deletions}
            </span>
          )}
        </div>
      </button>

      {/* Diff content */}
      {expanded && file.diff_content && (
        <div className="overflow-x-auto bg-black/50 border-t border-slate-800">
          <pre className="text-[11px] font-mono leading-[1.6] p-0">
            {file.diff_content.split('\n').map((line, i) => {
              let lineClass = 'text-slate-500 px-3'
              if (line.startsWith('+') && !line.startsWith('+++')) {
                lineClass = 'text-emerald-400 bg-emerald-500/8 px-3'
              } else if (line.startsWith('-') && !line.startsWith('---')) {
                lineClass = 'text-rose-400 bg-rose-500/8 px-3'
              } else if (line.startsWith('@@')) {
                lineClass = 'text-cyan-400/60 bg-cyan-500/5 px-3'
              } else if (line.startsWith('diff ')) {
                lineClass = 'text-slate-600 bg-slate-900/50 px-3 font-semibold'
              }
              return (
                <div key={i} className={clsx(lineClass, 'whitespace-pre')}>
                  {line || ' '}
                </div>
              )
            })}
          </pre>
        </div>
      )}
    </div>
  )
}

export function DiffPanel({
  open,
  onClose,
  title,
  subtitle,
  files,
  stats,
}: DiffPanelProps) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in data-[state=closed]:animate-out data-[state=closed]:fade-out" />
        <Dialog.Content
          className={clsx(
            'fixed right-0 top-0 z-50 h-full w-full max-w-[60vw] min-w-[480px]',
            'bg-[#0a0612] border-l border-slate-800',
            'flex flex-col overflow-hidden',
            'data-[state=open]:animate-in data-[state=open]:slide-in-from-right',
            'data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right',
            'duration-300',
          )}
        >
          {/* Header */}
          <div className="shrink-0 flex items-center justify-between px-5 py-4 border-b border-slate-800 bg-slate-900/40">
            <div className="min-w-0">
              <Dialog.Title className="text-base font-semibold text-white truncate">
                {title}
              </Dialog.Title>
              {subtitle && (
                <Dialog.Description className="text-xs font-mono text-slate-500 mt-0.5">
                  {subtitle}
                </Dialog.Description>
              )}
            </div>
            <div className="flex items-center gap-3 shrink-0">
              {/* Aggregate stats */}
              <div className="flex items-center gap-3 text-xs font-mono">
                <span className="text-slate-500">
                  {stats.files_changed} file{stats.files_changed !== 1 ? 's' : ''}
                </span>
                <span className="text-emerald-400 flex items-center gap-0.5">
                  <Plus className="w-3 h-3" />
                  {stats.additions}
                </span>
                <span className="text-rose-400 flex items-center gap-0.5">
                  <Minus className="w-3 h-3" />
                  {stats.deletions}
                </span>
              </div>
              <Dialog.Close asChild>
                <button className="p-1.5 rounded-md text-slate-500 hover:text-white hover:bg-slate-800 transition-colors">
                  <X className="w-4 h-4" />
                </button>
              </Dialog.Close>
            </div>
          </div>

          {/* File list */}
          <div className="flex-1 overflow-y-auto p-4 space-y-2">
            {files.length === 0 ? (
              <div className="text-center py-12 text-slate-600">
                <FileCode2 className="w-8 h-8 mx-auto mb-2 opacity-50" />
                <p className="text-sm">No diff data available</p>
              </div>
            ) : (
              files.map((file) => (
                <DiffFileSection key={file.path} file={file} />
              ))
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
