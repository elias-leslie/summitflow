'use client'

import { useQuery } from '@tanstack/react-query'
import {
  Box,
  CheckCircle2,
  Clock,
  Code2,
  Download,
  ExternalLink,
  GitCompare,
  History,
  Image as ImageIcon,
  LayoutTemplate,
  Loader2,
  Sparkles,
  X,
  XCircle,
} from 'lucide-react'
import Image from 'next/image'
import { useState } from 'react'
import {
  fetchMockupHistory,
  getMockupImageUrl,
  getScreenshotUrl,
  hasScreenshot,
  updateMockupStatus,
  type Mockup,
} from '@/lib/api/mockups'
import { ComparisonSlider } from './ComparisonSlider'

interface MockupDetailModalProps {
  mockup: Mockup
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onStatusChange: () => void
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
    label: 'Pending Approval',
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

export function MockupDetailModal({
  mockup,
  projectId,
  open,
  onOpenChange,
  onStatusChange,
}: MockupDetailModalProps) {
  const [updating, setUpdating] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [showComparison, setShowComparison] = useState(false)

  // Check if this mockup supports comparison (design-analyzer mockups have screenshots)
  const canCompare = hasScreenshot(mockup)

  // Fetch history
  const { data: history } = useQuery({
    queryKey: ['mockup-history', projectId, mockup.mockup_id],
    queryFn: () => fetchMockupHistory(projectId, mockup.mockup_id),
    enabled: open && showHistory,
  })

  if (!open) return null

  const status = statusConfig[mockup.status as keyof typeof statusConfig] ?? statusConfig.generated
  const StatusIcon = status.icon
  const TypeIcon = typeIcons[mockup.mockup_type as keyof typeof typeIcons] ?? Code2

  const handleStatusChange = async (newStatus: string) => {
    setUpdating(true)
    try {
      await updateMockupStatus(
        projectId,
        mockup.mockup_id,
        newStatus,
        newStatus === 'approved' ? 'user' : undefined,
      )
      onStatusChange()
      if (newStatus === 'rejected' || newStatus === 'archived') {
        onOpenChange(false)
      }
    } catch (error) {
      console.error('Failed to update status:', error)
    } finally {
      setUpdating(false)
    }
  }

  const formattedDate = mockup.created_at
    ? new Date(mockup.created_at).toLocaleString()
    : 'Unknown'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/80"
        onClick={() => onOpenChange(false)}
      />

      {/* Modal - Full screen with padding */}
      <div className="relative bg-slate-900 rounded-xl w-[95vw] max-w-[1600px] h-[90vh] overflow-hidden flex flex-col mx-4">
        {/* Header */}
        <div className="flex items-center justify-between p-3 border-b border-slate-800 flex-shrink-0">
          <div className="flex items-center gap-3">
            <TypeIcon className="w-5 h-5 text-outrun-400" />
            <h2 className="text-lg font-semibold text-white">{mockup.name}</h2>
            <div className={`flex items-center gap-1.5 px-2 py-1 rounded ${status.bg}`}>
              <StatusIcon className={`w-3.5 h-3.5 ${status.color}`} />
              <span className={`text-xs ${status.color}`}>{status.label}</span>
            </div>
          </div>
          <button
            onClick={() => onOpenChange(false)}
            className="p-2 text-slate-400 hover:text-white"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content - Image takes most space */}
        <div className="flex-1 overflow-hidden flex flex-col lg:flex-row min-h-0">
          {/* Preview - Large image area */}
          <div className="flex-1 p-4 flex flex-col min-h-0 min-w-0">
            <div className="flex-1 bg-slate-800 rounded-lg flex items-center justify-center relative min-h-0">
              {showComparison && canCompare ? (
                <ComparisonSlider
                  beforeImageUrl={getScreenshotUrl(projectId, mockup.mockup_id)}
                  afterImageUrl={getMockupImageUrl(projectId, mockup.mockup_id)}
                  beforeAlt="Original screenshot"
                  afterAlt={mockup.name}
                />
              ) : mockup.file_path ? (
                <Image
                  src={getMockupImageUrl(projectId, mockup.mockup_id)}
                  alt={mockup.name}
                  fill
                  className="object-contain p-2"
                  unoptimized
                />
              ) : mockup.content ? (
                <div className="w-full h-full p-4 overflow-auto text-white text-sm font-mono whitespace-pre-wrap">
                  {mockup.content}
                </div>
              ) : (
                <ImageIcon className="w-16 h-16 text-slate-600" />
              )}
            </div>

            {/* Actions below image */}
            <div className="flex items-center gap-2 mt-3 flex-shrink-0">
                {canCompare && (
                  <button
                    onClick={() => setShowComparison(!showComparison)}
                    className={`btn-secondary flex items-center gap-2 ${showComparison ? 'bg-amber-500/20 text-amber-400' : ''}`}
                  >
                    <GitCompare className="w-4 h-4" />
                    {showComparison ? 'Exit Compare' : 'Compare'}
                  </button>
                )}
                {mockup.file_path && (
                  <a
                    href={getMockupImageUrl(projectId, mockup.mockup_id)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn-secondary flex items-center gap-2"
                  >
                    <ExternalLink className="w-4 h-4" />
                    Open
                  </a>
                )}
                {mockup.file_path && (
                  <a
                    href={getMockupImageUrl(projectId, mockup.mockup_id)}
                    download={`${mockup.mockup_id}.png`}
                    className="btn-secondary flex items-center gap-2"
                  >
                    <Download className="w-4 h-4" />
                    Download
                  </a>
                )}
                <button
                  onClick={() => setShowHistory(!showHistory)}
                  className={`btn-secondary flex items-center gap-2 ${showHistory ? 'bg-outrun-500/20' : ''}`}
                >
                  <History className="w-4 h-4" />
                  History
                </button>
              </div>
          </div>

          {/* Details Sidebar */}
          <div className="w-80 flex-shrink-0 border-l border-slate-800 p-4 overflow-auto hidden lg:block">
            <div className="space-y-4">
              {/* Description */}
              {mockup.description && (
                <div>
                  <h3 className="text-sm font-medium text-slate-400 mb-1">
                    Description
                  </h3>
                  <p className="text-white">{mockup.description}</p>
                </div>
              )}

              {/* Metadata */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <h3 className="text-sm font-medium text-slate-400 mb-1">Type</h3>
                  <p className="text-white capitalize">{mockup.mockup_type}</p>
                </div>
                <div>
                  <h3 className="text-sm font-medium text-slate-400 mb-1">Version</h3>
                  <p className="text-white">{mockup.version}</p>
                </div>
                <div>
                  <h3 className="text-sm font-medium text-slate-400 mb-1">Created</h3>
                  <p className="text-white">{formattedDate}</p>
                </div>
                <div>
                  <h3 className="text-sm font-medium text-slate-400 mb-1">
                    Iteration
                  </h3>
                  <p className="text-white">{mockup.iteration_count}</p>
                </div>
              </div>

              {/* Provenance */}
              <div>
                <h3 className="text-sm font-medium text-slate-400 mb-2">
                  Provenance
                </h3>
                <div className="card p-3 space-y-2 text-sm">
                  {mockup.generator && (
                    <div className="flex justify-between">
                      <span className="text-slate-400">Generator</span>
                      <span className="text-white">{mockup.generator}</span>
                    </div>
                  )}
                  {mockup.generation_time_ms && (
                    <div className="flex justify-between">
                      <span className="text-slate-400">Generation Time</span>
                      <span className="text-white">
                        {mockup.generation_time_ms}ms
                      </span>
                    </div>
                  )}
                  {mockup.task_id && (
                    <div className="flex justify-between">
                      <span className="text-slate-400">Task</span>
                      <span className="text-white font-mono text-xs">
                        {mockup.task_id}
                      </span>
                    </div>
                  )}
                  {mockup.page_path && (
                    <div className="flex justify-between">
                      <span className="text-slate-400">Page</span>
                      <span className="text-white">{mockup.page_path}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Generation prompt */}
              {mockup.generation_prompt && (
                <div>
                  <h3 className="text-sm font-medium text-slate-400 mb-1">
                    Generation Prompt
                  </h3>
                  <div className="card p-3 text-sm text-slate-300 max-h-32 overflow-auto">
                    {mockup.generation_prompt}
                  </div>
                </div>
              )}

              {/* Status actions */}
              <div>
                <h3 className="text-sm font-medium text-slate-400 mb-2">
                  Change Status
                </h3>
                <div className="flex flex-wrap gap-2">
                  {mockup.status === 'generated' && (
                    <button
                      onClick={() => handleStatusChange('pending_approval')}
                      disabled={updating}
                      className="btn-secondary flex items-center gap-2"
                    >
                      {updating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Clock className="w-4 h-4" />}
                      Submit for Review
                    </button>
                  )}
                  {(mockup.status === 'generated' || mockup.status === 'pending_approval') && (
                    <>
                      <button
                        onClick={() => handleStatusChange('approved')}
                        disabled={updating}
                        className="btn-primary flex items-center gap-2"
                      >
                        {updating ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
                        Approve
                      </button>
                      <button
                        onClick={() => handleStatusChange('rejected')}
                        disabled={updating}
                        className="btn-secondary text-rose-400 hover:bg-rose-500/10 flex items-center gap-2"
                      >
                        {updating ? <Loader2 className="w-4 h-4 animate-spin" /> : <XCircle className="w-4 h-4" />}
                        Reject
                      </button>
                    </>
                  )}
                  {mockup.status === 'approved' && (
                    <button
                      onClick={() => handleStatusChange('applied')}
                      disabled={updating}
                      className="btn-primary flex items-center gap-2"
                    >
                      {updating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Box className="w-4 h-4" />}
                      Mark as Applied
                    </button>
                  )}
                </div>
              </div>

              {/* History panel */}
              {showHistory && history && (
                <div>
                  <h3 className="text-sm font-medium text-slate-400 mb-2">
                    Version History
                  </h3>
                  <div className="space-y-2">
                    {history.map((item) => (
                      <div
                        key={item.mockup_id}
                        className={`card p-2 flex items-center gap-3 text-sm ${
                          item.mockup_id === mockup.mockup_id
                            ? 'ring-1 ring-outrun-500'
                            : ''
                        }`}
                      >
                        <span className="text-slate-400">v{item.version}</span>
                        <span className="text-white flex-1 truncate">
                          {item.name}
                        </span>
                        <span className="text-slate-500 text-xs">
                          {item.created_at
                            ? new Date(item.created_at).toLocaleDateString()
                            : ''}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
