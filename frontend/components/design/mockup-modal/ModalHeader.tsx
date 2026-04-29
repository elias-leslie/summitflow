'use client'

import clsx from 'clsx'
import { ChevronLeft, ChevronRight, Code2, X } from 'lucide-react'
import type { Mockup } from '@/lib/api/mockups'
import { statusConfig, typeIcons } from './config'

export interface MockupModalNavigation {
  currentIndex: number
  totalCount: number
  canGoPrevious: boolean
  canGoNext: boolean
  onPrevious: () => void
  onNext: () => void
}

interface ModalHeaderProps {
  mockup: Mockup
  navigation?: MockupModalNavigation
  onClose: () => void
}

export function ModalHeader({ mockup, navigation, onClose }: ModalHeaderProps) {
  const status =
    statusConfig[mockup.status as keyof typeof statusConfig] ??
    statusConfig.generated
  const StatusIcon = status.icon
  const TypeIcon =
    typeIcons[mockup.mockup_type as keyof typeof typeIcons] ?? Code2

  return (
    <div className="flex items-center justify-between gap-3 p-3 border-b border-slate-800 flex-shrink-0">
      <div className="flex min-w-0 items-center gap-3">
        <TypeIcon className="w-5 h-5 text-outrun-400" />
        <h2 className="truncate text-lg font-semibold text-slate-100 display">
          {mockup.name}
        </h2>
        <div
          className={clsx(
            'flex items-center gap-1.5 px-2 py-1 rounded',
            status.bg,
          )}
        >
          <StatusIcon className={clsx('w-3.5 h-3.5', status.color)} />
          <span className={clsx('text-xs', status.color)}>{status.label}</span>
        </div>
      </div>
      <div className="flex flex-shrink-0 items-center gap-1.5">
        {navigation && (
          <>
            <button
              type="button"
              onClick={navigation.onPrevious}
              disabled={!navigation.canGoPrevious}
              aria-label="Previous mockup"
              className="flex h-9 w-9 items-center justify-center rounded border border-slate-700 text-slate-300 hover:border-slate-500 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft className="h-5 w-5" />
            </button>
            <span className="min-w-16 text-center text-xs text-slate-400">
              {navigation.currentIndex} of {navigation.totalCount}
            </span>
            <button
              type="button"
              onClick={navigation.onNext}
              disabled={!navigation.canGoNext}
              aria-label="Next mockup"
              className="flex h-9 w-9 items-center justify-center rounded border border-slate-700 text-slate-300 hover:border-slate-500 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronRight className="h-5 w-5" />
            </button>
          </>
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="flex h-9 w-9 items-center justify-center text-slate-400 hover:text-slate-100"
        >
          <X className="w-5 h-5" />
        </button>
      </div>
    </div>
  )
}
