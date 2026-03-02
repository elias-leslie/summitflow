'use client'

import { FileEdit, FileMinus, FilePlus, FileText } from 'lucide-react'
import type { SpecRecord } from './SpecRendererTypes'

/** Operation badge for file specs */
function OperationBadge({ operation }: { operation: string }) {
  const op = operation.toLowerCase()
  const config: Record<
    string,
    { icon: typeof FileText; color: string; label: string }
  > = {
    create: {
      icon: FilePlus,
      color: 'bg-emerald-500/20 text-emerald-400',
      label: 'CREATE',
    },
    modify: {
      icon: FileEdit,
      color: 'bg-amber-500/20 text-amber-400',
      label: 'MODIFY',
    },
    update: {
      icon: FileEdit,
      color: 'bg-amber-500/20 text-amber-400',
      label: 'UPDATE',
    },
    delete: {
      icon: FileMinus,
      color: 'bg-red-500/20 text-red-400',
      label: 'DELETE',
    },
    read: {
      icon: FileText,
      color: 'bg-blue-500/20 text-blue-400',
      label: 'READ',
    },
  }
  const {
    icon: Icon,
    color,
    label,
  } = config[op] || {
    icon: FileText,
    color: 'bg-slate-500/20 text-slate-400',
    label: op.toUpperCase(),
  }

  return (
    <span
      className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-2xs font-semibold ${color}`}
    >
      <Icon className="w-3 h-3" />
      {label}
    </span>
  )
}

/** File spec renderer with clickable path and operation badge */
export function FileSpecRenderer({ spec }: { spec: SpecRecord }) {
  const filePath =
    (spec.file as string) ||
    (spec.filepath as string) ||
    (spec.file_path as string) ||
    (spec.path as string) ||
    (spec.filename as string) ||
    ''
  const operation =
    (spec.operation as string) ||
    (spec.action as string) ||
    (spec.create
      ? 'create'
      : spec.modify
        ? 'modify'
        : spec.delete
          ? 'delete'
          : '')

  const otherFields = Object.entries(spec).filter(
    ([key]) =>
      ![
        'file',
        'filepath',
        'file_path',
        'path',
        'filename',
        'operation',
        'action',
        'create',
        'modify',
        'delete',
      ].includes(key.toLowerCase()),
  )

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <FileText className="w-3.5 h-3.5 text-orange-400" />
        {operation && <OperationBadge operation={operation} />}
        <code className="text-xs text-slate-200 bg-slate-800/60 px-2 py-0.5 rounded font-mono truncate max-w-xs">
          {filePath || '(no file path)'}
        </code>
      </div>
      {otherFields.length > 0 && (
        <div className="pl-5 space-y-1">
          {otherFields.map(([key, value]) => (
            <div key={key} className="flex gap-2 text-2xs">
              <span className="text-slate-500 font-mono">{key}:</span>
              <span className="text-amber-300/80">
                {typeof value === 'string' ? value : JSON.stringify(value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
