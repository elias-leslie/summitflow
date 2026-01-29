'use client'

import {
  ArrowUpCircle,
  Box,
  Check,
  CheckCircle2,
  Clock,
  Code2,
  Image as ImageIcon,
  LayoutTemplate,
  Sparkles,
  XCircle,
} from 'lucide-react'
import Image from 'next/image'
import { hasScreenshot, type Mockup } from '@/lib/api/mockups'

interface MockupCardProps {
  mockup: Mockup
  viewMode: 'grid' | 'list'
  onClick: () => void
  selectMode?: boolean
  isSelected?: boolean
}

const statusConfig = {
  generated: {
    icon: Sparkles,
    color: 'text-blue-400',
    bg: 'bg-blue-500/10',
    label: 'Generated',
  },
  pending_approval: {
    icon: Clock,
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
    label: 'Pending',
  },
  approved: {
    icon: CheckCircle2,
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10',
    label: 'Approved',
  },
  rejected: {
    icon: XCircle,
    color: 'text-rose-400',
    bg: 'bg-rose-500/10',
    label: 'Rejected',
  },
  applied: {
    icon: Box,
    color: 'text-purple-400',
    bg: 'bg-purple-500/10',
    label: 'Applied',
  },
  archived: {
    icon: Box,
    color: 'text-slate-400',
    bg: 'bg-slate-500/10',
    label: 'Archived',
  },
}

const typeIcons = {
  component: Code2,
  page: LayoutTemplate,
  layout: LayoutTemplate,
  icon: ImageIcon,
  illustration: ImageIcon,
}

export function MockupCard({
  mockup,
  viewMode,
  onClick,
  selectMode = false,
  isSelected = false,
}: MockupCardProps) {
  const status =
    statusConfig[mockup.status as keyof typeof statusConfig] ??
    statusConfig.generated
  const StatusIcon = status.icon
  const TypeIcon =
    typeIcons[mockup.mockup_type as keyof typeof typeIcons] ?? Code2
  const isImprovement = hasScreenshot(mockup)

  const formattedDate = mockup.created_at
    ? new Date(mockup.created_at).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : 'Unknown'

  if (viewMode === 'list') {
    return (
      <div
        onClick={onClick}
        className={`card p-4 flex items-center gap-4 cursor-pointer transition-colors ${
          selectMode && isSelected
            ? 'bg-outrun-500/10 border-outrun-500/50 ring-2 ring-outrun-500/30'
            : 'hover:bg-slate-700/50'
        }`}
      >
        {/* Checkbox */}
        {selectMode && (
          <div
            className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-all ${
              isSelected
                ? 'bg-outrun-500 border-outrun-500'
                : 'border-slate-600 hover:border-outrun-400'
            }`}
          >
            {isSelected && <Check className="w-3.5 h-3.5 text-white" />}
          </div>
        )}

        {/* Thumbnail placeholder */}
        <div className="w-16 h-12 bg-slate-700 rounded flex items-center justify-center flex-shrink-0">
          <TypeIcon className="w-6 h-6 text-slate-500" />
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <h3 className="text-white font-medium truncate">{mockup.name}</h3>
          {mockup.description && (
            <p className="text-slate-400 text-sm truncate">
              {mockup.description}
            </p>
          )}
        </div>

        {/* Badges */}
        <div className="flex items-center gap-2">
          {isImprovement && (
            <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-gradient-to-r from-amber-500/10 to-cyan-500/10">
              <ArrowUpCircle className="w-3.5 h-3.5 text-amber-400" />
              <span className="text-xs text-amber-400">Improvement</span>
            </div>
          )}
          <div
            className={`flex items-center gap-1.5 px-2 py-1 rounded ${status.bg}`}
          >
            <StatusIcon className={`w-3.5 h-3.5 ${status.color}`} />
            <span className={`text-xs ${status.color}`}>{status.label}</span>
          </div>
        </div>

        {/* Meta */}
        <div className="flex items-center gap-4 text-slate-400 text-xs">
          <span className="capitalize">{mockup.mockup_type}</span>
          <span>v{mockup.version}</span>
          <span>{formattedDate}</span>
        </div>
      </div>
    )
  }

  // Grid view
  return (
    <div
      onClick={onClick}
      className={`card overflow-hidden cursor-pointer transition-all group ${
        selectMode && isSelected
          ? 'ring-2 ring-outrun-500 bg-outrun-500/5'
          : 'hover:ring-2 hover:ring-outrun-500/50'
      }`}
    >
      {/* Thumbnail */}
      <div className="aspect-video bg-slate-800 flex items-center justify-center relative">
        {/* Checkbox overlay */}
        {selectMode && (
          <div className="absolute top-2 left-2 z-10">
            <div
              className={`w-6 h-6 rounded border-2 flex items-center justify-center transition-all backdrop-blur-sm ${
                isSelected
                  ? 'bg-outrun-500 border-outrun-500 shadow-lg shadow-outrun-500/50'
                  : 'bg-slate-900/80 border-slate-600 hover:border-outrun-400'
              }`}
            >
              {isSelected && <Check className="w-4 h-4 text-white" />}
            </div>
          </div>
        )}
        {mockup.file_path ? (
          <Image
            src={`/api/projects/${mockup.project_id}/mockups/${mockup.mockup_id}/image`}
            alt={mockup.name}
            fill
            className="object-cover"
            unoptimized
          />
        ) : (
          <TypeIcon className="w-12 h-12 text-slate-600" />
        )}

        {/* Badges overlay */}
        <div className="absolute top-2 right-2 flex items-center gap-1.5">
          {isImprovement && (
            <div className="flex items-center gap-1 px-2 py-1 rounded bg-gradient-to-r from-amber-500/20 to-cyan-500/20 backdrop-blur-sm">
              <ArrowUpCircle className="w-3 h-3 text-amber-400" />
              <span className="text-xs text-amber-400">Improvement</span>
            </div>
          )}
          <div
            className={`flex items-center gap-1 px-2 py-1 rounded ${status.bg} backdrop-blur-sm`}
          >
            <StatusIcon className={`w-3 h-3 ${status.color}`} />
            <span className={`text-xs ${status.color}`}>{status.label}</span>
          </div>
        </div>

        {/* Version badge */}
        {mockup.version > 1 && (
          <div className="absolute bottom-2 right-2 bg-slate-900/80 px-1.5 py-0.5 rounded text-xs text-slate-300">
            v{mockup.version}
          </div>
        )}
      </div>

      {/* Info */}
      <div className="p-3">
        <h3 className="text-white font-medium truncate group-hover:text-outrun-400 transition-colors">
          {mockup.name}
        </h3>
        {mockup.description && (
          <p className="text-slate-400 text-sm truncate mt-1">
            {mockup.description}
          </p>
        )}
        <div className="flex items-center gap-3 mt-2 text-xs text-slate-500">
          <span className="capitalize">{mockup.mockup_type}</span>
          {mockup.generator && <span>{mockup.generator}</span>}
          <span>{formattedDate}</span>
        </div>
      </div>
    </div>
  )
}
