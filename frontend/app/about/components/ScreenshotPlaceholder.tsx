import { Camera } from 'lucide-react'

import type { ScreenshotPlaceholderProps } from './types'

export function ScreenshotPlaceholder({
  label,
  description,
  dark,
}: ScreenshotPlaceholderProps): React.ReactElement {
  return (
    <div
      className="relative rounded-xl overflow-hidden border border-slate-700"
      style={{
        aspectRatio: '16/10',
        background: dark
          ? 'linear-gradient(135deg, #0a0612 0%, #150d20 100%)'
          : 'linear-gradient(135deg, #1a0a2e 0%, #251538 100%)',
      }}
    >
      {/* Simulated window chrome */}
      <div className="absolute top-0 left-0 right-0 h-8 bg-slate-900/80 flex items-center px-3 gap-2">
        <div className="w-3 h-3 rounded-full bg-rose-500/60" />
        <div className="w-3 h-3 rounded-full bg-amber-500/60" />
        <div className="w-3 h-3 rounded-full bg-emerald-500/60" />
        <span className="ml-4 text-xs text-slate-500 mono">{label}</span>
      </div>

      {/* Content area with grid pattern */}
      <div
        className="absolute inset-0 top-8 flex items-center justify-center"
        style={{
          backgroundImage: `
            linear-gradient(to right, rgba(255, 0, 102, 0.05) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(255, 0, 102, 0.05) 1px, transparent 1px)
          `,
          backgroundSize: '24px 24px',
        }}
      >
        <div className="text-center p-8">
          <div
            className="w-16 h-16 rounded-2xl mx-auto mb-4 flex items-center justify-center"
            style={{
              background:
                'linear-gradient(135deg, rgba(255, 102, 0, 0.1) 0%, rgba(255, 0, 102, 0.1) 100%)',
              border: '1px solid rgba(255, 102, 0, 0.2)',
            }}
          >
            <Camera className="w-8 h-8 text-slate-600" />
          </div>
          <p className="text-slate-500 text-sm">{description}</p>
          <p className="text-slate-600 text-xs mt-2 mono">
            Screenshot placeholder
          </p>
        </div>
      </div>
    </div>
  )
}
