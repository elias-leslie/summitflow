'use client'

import clsx from 'clsx'
import {
  Download,
  ExternalLink,
  GitCompare,
  History,
  Image as ImageIcon,
  Layers3,
  Trash2,
} from 'lucide-react'
import Image from 'next/image'
import type { Mockup } from '@/lib/api/mockups'
import { getMockupImageUrl, getScreenshotUrl } from '@/lib/api/mockups'
import { ComparisonSlider } from '../ComparisonSlider'

function isHtmlContent(content: string): boolean {
  const trimmed = content.trimStart()
  return (
    trimmed.startsWith('<!') ||
    trimmed.startsWith('<html') ||
    trimmed.startsWith('<HTML')
  )
}

interface PreviewAreaProps {
  mockup: Mockup
  projectId: string
  showComparison: boolean
  showHistory: boolean
  canCompare: boolean
  onToggleComparison: () => void
  onToggleHistory: () => void
  onCreateIteration: () => void
  onDelete: () => void
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
  onDelete,
}: PreviewAreaProps) {
  return (
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
          isHtmlContent(mockup.content) ? (
            <iframe
              srcDoc={mockup.content}
              title={mockup.name}
              sandbox="allow-same-origin"
              className="w-full h-full rounded-lg border-0"
            />
          ) : (
            <div className="w-full h-full p-4 overflow-auto text-slate-100 text-sm font-mono whitespace-pre-wrap">
              {mockup.content}
            </div>
          )
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
              href={getMockupImageUrl(projectId, mockup.mockup_id)}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary flex items-center gap-2"
            >
              <ExternalLink className="w-4 h-4" />
              Open
            </a>
            <a
              href={getMockupImageUrl(projectId, mockup.mockup_id)}
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
        <button
          type="button"
          onClick={onCreateIteration}
          className="btn-secondary flex items-center gap-2"
        >
          <Layers3 className="w-4 h-4" />
          New Iteration
        </button>
        <div className="flex-1" />
        <button
          type="button"
          onClick={onDelete}
          className="btn-secondary flex items-center gap-2 text-rose-400 hover:bg-rose-500/10 border-rose-500/30"
        >
          <Trash2 className="w-4 h-4" />
          Delete
        </button>
      </div>
    </div>
  )
}
