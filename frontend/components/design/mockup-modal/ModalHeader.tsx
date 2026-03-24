'use client'

import clsx from 'clsx'
import { X } from 'lucide-react'
import type { Mockup } from '@/lib/api/mockups'
import { statusConfig, typeIcons } from './config'
import { Code2 } from 'lucide-react'

interface ModalHeaderProps {
  mockup: Mockup
  onClose: () => void
}

export function ModalHeader({ mockup, onClose }: ModalHeaderProps) {
  const status =
    statusConfig[mockup.status as keyof typeof statusConfig] ??
    statusConfig.generated
  const StatusIcon = status.icon
  const TypeIcon =
    typeIcons[mockup.mockup_type as keyof typeof typeIcons] ?? Code2

  return (
    <div className="flex items-center justify-between p-3 border-b border-slate-800 flex-shrink-0">
      <div className="flex items-center gap-3">
        <TypeIcon className="w-5 h-5 text-outrun-400" />
        <h2 className="text-lg font-semibold text-slate-100 display">{mockup.name}</h2>
        <div
          className={clsx('flex items-center gap-1.5 px-2 py-1 rounded', status.bg)}
        >
          <StatusIcon className={clsx('w-3.5 h-3.5', status.color)} />
          <span className={clsx('text-xs', status.color)}>{status.label}</span>
        </div>
      </div>
      <button type="button" onClick={onClose} aria-label="Close" className="p-2 text-slate-400 hover:text-slate-100">
        <X className="w-5 h-5" />
      </button>
    </div>
  )
}
