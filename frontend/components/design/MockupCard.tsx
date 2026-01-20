'use client'

import {
  Box,
  CheckCircle2,
  Clock,
  Code2,
  Image as ImageIcon,
  LayoutTemplate,
  Sparkles,
  XCircle,
} from 'lucide-react'
import Image from 'next/image'
import type { Mockup } from '@/lib/api/mockups'

interface MockupCardProps {
  mockup: Mockup
  viewMode: 'grid' | 'list'
  onClick: () => void
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

export function MockupCard({ mockup, viewMode, onClick }: MockupCardProps) {
  const status = statusConfig[mockup.status as keyof typeof statusConfig] ?? statusConfig.generated
  const StatusIcon = status.icon
  const TypeIcon = typeIcons[mockup.mockup_type as keyof typeof typeIcons] ?? Code2

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
        className="card p-4 flex items-center gap-4 cursor-pointer hover:bg-slate-700/50 transition-colors"
      >
        {/* Thumbnail placeholder */}
        <div className="w-16 h-12 bg-slate-700 rounded flex items-center justify-center flex-shrink-0">
          <TypeIcon className="w-6 h-6 text-slate-500" />
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <h3 className="text-white font-medium truncate">{mockup.name}</h3>
          {mockup.description && (
            <p className="text-slate-400 text-sm truncate">{mockup.description}</p>
          )}
        </div>

        {/* Status badge */}
        <div className={`flex items-center gap-1.5 px-2 py-1 rounded ${status.bg}`}>
          <StatusIcon className={`w-3.5 h-3.5 ${status.color}`} />
          <span className={`text-xs ${status.color}`}>{status.label}</span>
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
      className="card overflow-hidden cursor-pointer hover:ring-2 hover:ring-outrun-500/50 transition-all group"
    >
      {/* Thumbnail */}
      <div className="aspect-video bg-slate-800 flex items-center justify-center relative">
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

        {/* Status overlay */}
        <div
          className={`absolute top-2 right-2 flex items-center gap-1 px-2 py-1 rounded ${status.bg}`}
        >
          <StatusIcon className={`w-3 h-3 ${status.color}`} />
          <span className={`text-xs ${status.color}`}>{status.label}</span>
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
          <p className="text-slate-400 text-sm truncate mt-1">{mockup.description}</p>
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
