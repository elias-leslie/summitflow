'use client'

import clsx from 'clsx'
import type { SurfaceFrameProps } from './types'

export function SurfaceFrames({
  compareMode,
  content,
  mockup,
  draftKey,
  iframeRef,
  onLoad,
}: SurfaceFrameProps) {
  return (
    <div
      className={clsx(
        'grid min-h-0 flex-1 bg-[#07040d]',
        compareMode === 'split' && 'lg:grid-cols-2',
      )}
    >
      {compareMode !== 'current' ? (
        <div className="relative min-h-0 border-r border-slate-800">
          <div className="absolute left-2 top-2 z-10 rounded border border-slate-700 bg-slate-950/85 px-2 py-1 text-xs text-slate-300">
            Original
          </div>
          <iframe
            srcDoc={content}
            title={`${mockup.name} original`}
            sandbox="allow-same-origin"
            className="h-full w-full border-0 bg-white"
          />
        </div>
      ) : null}
      {compareMode !== 'original' ? (
        <div className="relative min-h-0">
          <div className="absolute left-2 top-2 z-10 rounded border border-phosphor-500/30 bg-slate-950/85 px-2 py-1 text-xs text-phosphor-200">
            Editable surface
          </div>
          <iframe
            key={`${mockup.mockup_id}-${draftKey}`}
            ref={iframeRef}
            srcDoc={content}
            title={`${mockup.name} editable`}
            sandbox="allow-same-origin"
            onLoad={onLoad}
            className="h-full w-full border-0 bg-white"
          />
        </div>
      ) : null}
    </div>
  )
}
