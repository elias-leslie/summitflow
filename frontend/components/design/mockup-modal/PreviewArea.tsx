'use client'

import clsx from 'clsx'
import {
  Download,
  ExternalLink,
  GitCompare,
  History,
  Image as ImageIcon,
  Layers3,
  PanelsTopLeft,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import Image from 'next/image'
import type { Mockup } from '@/lib/api/mockups'
import { getMockupImageUrl, getScreenshotUrl } from '@/lib/api/mockups'
import { isHtmlMockupContent } from '@/lib/mockup-html'
import { ComparisonSlider } from '../ComparisonSlider'
import { MockupSurfaceEditor } from './MockupSurfaceEditor'

interface PreviewAreaProps {
  mockup: Mockup
  projectId: string
  showComparison: boolean
  showHistory: boolean
  canCompare: boolean
  onToggleComparison: () => void
  onToggleHistory: () => void
  onCreateIteration: () => void
  onRerun: () => void
  onDelete: () => void
  onVersionCreated?: (mockup: Mockup) => void
  onSendToJenny?: (payload: {
    sourceMockup: Mockup
    savedMockup?: Mockup
    summary: string
  }) => void
  readOnly?: boolean
  getImageUrl?: (projectId: string, mockupId: string) => string
  getScreenshotUrl?: (projectId: string, mockupId: string) => string
}

export function PreviewArea({
  mockup,
  projectId,
  showComparison,
  showHistory,
  canCompare,
  onToggleComparison,
  onToggleHistory,
  onCreateIteration,
  onRerun,
  onDelete,
  onVersionCreated,
  onSendToJenny,
  readOnly = false,
  getImageUrl = getMockupImageUrl,
  getScreenshotUrl: screenshotUrl = getScreenshotUrl,
}: PreviewAreaProps) {
  const openWorkChat = () => {
    const params = new URLSearchParams({
      project_id: projectId,
      design_id: mockup.mockup_id,
      artifact_summary: mockup.name,
    })
    window.open(`/work-chats?${params.toString()}`, '_blank')
  }

  const imageUrl = getImageUrl(projectId, mockup.mockup_id)

  return (
    <div className="flex-1 p-4 flex flex-col min-h-0 min-w-0">
      <div className="flex-1 bg-slate-800 rounded-lg flex items-center justify-center relative min-h-0">
        {showComparison && canCompare ? (
          <ComparisonSlider
            beforeImageUrl={screenshotUrl(projectId, mockup.mockup_id)}
            afterImageUrl={imageUrl}
            beforeAlt="Original screenshot"
            afterAlt={mockup.name}
          />
        ) : isHtmlMockupContent(mockup.content) && !readOnly ? (
          <MockupSurfaceEditor
            mockup={mockup}
            projectId={projectId}
            onSaved={onVersionCreated}
            onSendToJenny={onSendToJenny}
          />
        ) : isHtmlMockupContent(mockup.content) ? (
          <iframe
            title={mockup.name}
            srcDoc={mockup.content ?? ''}
            sandbox=""
            className="h-full w-full rounded-lg border-0 bg-white"
          />
        ) : mockup.file_path ? (
          <Image
            src={imageUrl}
            alt={mockup.name}
            fill
            className="object-contain p-2"
            unoptimized
          />
        ) : mockup.content ? (
          <div className="w-full h-full p-4 overflow-auto text-slate-100 text-sm font-mono whitespace-pre-wrap">
            {mockup.content}
          </div>
        ) : (
          <ImageIcon className="w-16 h-16 text-slate-600" />
        )}
      </div>

      <div className="flex items-center gap-2 mt-3 flex-shrink-0">
        {canCompare && (
          <button
            type="button"
            onClick={onToggleComparison}
            className={clsx(
              'btn-secondary flex items-center gap-2',
              showComparison && 'bg-amber-500/20 text-amber-400',
            )}
          >
            <GitCompare className="w-4 h-4" />
            {showComparison ? 'Exit Compare' : 'Compare'}
          </button>
        )}
        {mockup.file_path && (
          <>
            <a
              href={imageUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary flex items-center gap-2"
            >
              <ExternalLink className="w-4 h-4" />
              Open
            </a>
            <a
              href={imageUrl}
              download={`${mockup.mockup_id}.png`}
              className="btn-secondary flex items-center gap-2"
            >
              <Download className="w-4 h-4" />
              Download
            </a>
          </>
        )}
        <button
          type="button"
          onClick={onToggleHistory}
          className={clsx(
            'btn-secondary flex items-center gap-2',
            showHistory && 'bg-outrun-500/20',
          )}
        >
          <History className="w-4 h-4" />
          History
        </button>
        {!readOnly && (
          <>
            <button
              type="button"
              onClick={onRerun}
              className="btn-secondary flex items-center gap-2"
            >
              <RefreshCw className="w-4 h-4" />
              Rerun
            </button>
            <button
              type="button"
              onClick={onCreateIteration}
              className="btn-secondary flex items-center gap-2"
            >
              <Layers3 className="w-4 h-4" />
              New Iteration
            </button>
            <button
              type="button"
              onClick={openWorkChat}
              className="btn-secondary flex items-center gap-2"
            >
              <PanelsTopLeft className="w-4 h-4" />
              Work Chat
            </button>
          </>
        )}
        <div className="flex-1" />
        {!readOnly && (
          <button
            type="button"
            onClick={onDelete}
            className="btn-secondary flex items-center gap-2 text-rose-400 hover:bg-rose-500/10 border-rose-500/30"
          >
            <Trash2 className="w-4 h-4" />
            Delete
          </button>
        )}
      </div>
    </div>
  )
}
