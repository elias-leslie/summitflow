'use client'

import { AlertCircle, CheckCircle2 } from 'lucide-react'
import type { AnalyzePageResponse } from '@/lib/api/mockups'

interface AnalysisResultProps {
  result: AnalyzePageResponse
}

export function AnalysisResult({ result }: AnalysisResultProps) {
  if (result.success) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-emerald-400">
          <CheckCircle2 className="w-5 h-5" />
          <span className="font-medium">Analysis & Mockup Complete</span>
        </div>
        <div className="grid grid-cols-3 gap-4 text-sm">
          <div className="card p-3">
            <div className="text-slate-400 mb-1">Mockup ID</div>
            <div className="text-slate-100 font-mono text-xs">
              {result.mockup_id}
            </div>
          </div>
          <div className="card p-3">
            <div className="text-slate-400 mb-1">Issues Found</div>
            <div className="text-slate-100">{result.issues_found}</div>
          </div>
          <div className="card p-3">
            <div className="text-slate-400 mb-1">Mockup Image</div>
            <div className="text-slate-100 text-xs">
              {result.mockup_image_path ? '✓ Generated' : '—'}
            </div>
          </div>
        </div>
        {result.recommendations && (
          <div>
            <div className="text-sm font-medium text-slate-300 mb-2">
              Recommendations Preview
            </div>
            <div className="card p-3 max-h-48 overflow-auto">
              <pre className="text-xs text-slate-300 whitespace-pre-wrap">
                {result.recommendations.slice(0, 1000)}
                {result.recommendations.length > 1000 && '...'}
              </pre>
            </div>
          </div>
        )}
        <p className="text-sm text-slate-400">
          View the full analysis in the mockup detail modal.
        </p>
      </div>
    )
  }

  return (
    <div className="flex items-start gap-3 p-4 bg-rose-950/30 border border-rose-500/30 rounded-lg">
      <AlertCircle className="w-5 h-5 text-rose-400 flex-shrink-0" />
      <div>
        <div className="text-rose-400 font-medium">Analysis Failed</div>
        <div className="text-slate-400 text-sm mt-1">{result.error}</div>
      </div>
    </div>
  )
}
