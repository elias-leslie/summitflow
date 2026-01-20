'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  Scan,
  Sparkles,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { analyzePage, type AnalyzePageResponse } from '@/lib/api/mockups'

interface GenerateMockupDialogProps {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  defaultUrl?: string
}

export function GenerateMockupDialog({
  projectId,
  open,
  onOpenChange,
  defaultUrl = '',
}: GenerateMockupDialogProps) {
  const [pageUrl, setPageUrl] = useState(defaultUrl)
  const [result, setResult] = useState<AnalyzePageResponse | null>(null)
  const queryClient = useQueryClient()

  const analyzeMutation = useMutation({
    mutationFn: () => analyzePage(projectId, pageUrl),
    onSuccess: (data) => {
      setResult(data)
      if (data.success) {
        queryClient.invalidateQueries({ queryKey: ['mockups', projectId] })
        queryClient.invalidateQueries({ queryKey: ['mockup-stats', projectId] })
      }
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!pageUrl.trim()) return
    setResult(null)
    analyzeMutation.mutate()
  }

  const handleClose = () => {
    setPageUrl(defaultUrl)
    setResult(null)
    analyzeMutation.reset()
    onOpenChange(false)
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/80"
        onClick={handleClose}
      />

      {/* Dialog */}
      <div className="relative bg-slate-900 rounded-xl w-full max-w-2xl mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <Sparkles className="w-5 h-5 text-outrun-400" />
            <h2 className="text-lg font-semibold text-white">
              Generate Design Mockup
            </h2>
          </div>
          <button
            onClick={handleClose}
            className="p-2 text-slate-400 hover:text-white"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6">
          <p className="text-slate-400 mb-6">
            Analyze a page against design standards and generate improvement
            recommendations. The page will be captured and analyzed using Claude
            vision.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Page URL
              </label>
              <input
                type="url"
                value={pageUrl}
                onChange={(e) => setPageUrl(e.target.value)}
                placeholder="http://localhost:3001/projects/summitflow/settings"
                className="w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-outrun-500"
                disabled={analyzeMutation.isPending}
              />
              <p className="mt-1 text-xs text-slate-500">
                Enter the full URL of the page you want to analyze
              </p>
            </div>

            {/* Quick URLs */}
            <div className="flex flex-wrap gap-2">
              <span className="text-xs text-slate-400">Quick select:</span>
              {[
                { label: 'Settings', url: 'http://localhost:3001/projects/summitflow/settings' },
                { label: 'Design', url: 'http://localhost:3001/projects/summitflow/design' },
                { label: 'Tasks', url: 'http://localhost:3001/projects/summitflow/tasks' },
              ].map((item) => (
                <button
                  key={item.label}
                  type="button"
                  onClick={() => setPageUrl(item.url)}
                  className="text-xs px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                >
                  {item.label}
                </button>
              ))}
            </div>

            {/* Submit button */}
            <div className="flex justify-end gap-3 pt-4">
              <button
                type="button"
                onClick={handleClose}
                className="btn-secondary"
                disabled={analyzeMutation.isPending}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!pageUrl.trim() || analyzeMutation.isPending}
                className="btn-primary flex items-center gap-2"
              >
                {analyzeMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Analyzing...
                  </>
                ) : (
                  <>
                    <Scan className="w-4 h-4" />
                    Analyze Page
                  </>
                )}
              </button>
            </div>
          </form>

          {/* Result */}
          {result && (
            <div className="mt-6 border-t border-slate-800 pt-6">
              {result.success ? (
                <div className="space-y-4">
                  <div className="flex items-center gap-2 text-emerald-400">
                    <CheckCircle2 className="w-5 h-5" />
                    <span className="font-medium">Analysis & Mockup Complete</span>
                  </div>
                  <div className="grid grid-cols-3 gap-4 text-sm">
                    <div className="card p-3">
                      <div className="text-slate-400 mb-1">Mockup ID</div>
                      <div className="text-white font-mono text-xs">
                        {result.mockup_id}
                      </div>
                    </div>
                    <div className="card p-3">
                      <div className="text-slate-400 mb-1">Issues Found</div>
                      <div className="text-white">{result.issues_found}</div>
                    </div>
                    <div className="card p-3">
                      <div className="text-slate-400 mb-1">Mockup Image</div>
                      <div className="text-white text-xs">
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
              ) : (
                <div className="flex items-start gap-3 p-4 bg-rose-950/30 border border-rose-500/30 rounded-lg">
                  <AlertCircle className="w-5 h-5 text-rose-400 flex-shrink-0" />
                  <div>
                    <div className="text-rose-400 font-medium">
                      Analysis Failed
                    </div>
                    <div className="text-slate-400 text-sm mt-1">
                      {result.error}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
